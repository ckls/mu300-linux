"""Temporary-only CLI/index compatibility tests; no device transports."""
import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import threading
from contextlib import redirect_stdout, redirect_stderr
import zipfile

TOP = next(p for p in Path(__file__).resolve().parents if (p/'installer').is_dir())
sys.path[:0] = [str(TOP/'installer/tests'), str(TOP/'installer')]
from backend.ota_package import Release, analyze
from backend.release_index import snapshot, write_index, read_index
from test_ota import mu_release

TOOL = Path(__file__).with_name('release-index.py')
if not TOOL.exists():
    TOOL = TOP/'tools/release-index.py'
spec = importlib.util.spec_from_file_location('release_summary', TOOL)
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, number=1, boot=b'boot'):
        release = self.root/str(number)
        meta = dict(profile='mu300', image_version='mu300-r'+str(number), kernel_release='7.2.8', openwrt='25.12.5')
        mu_release(release, meta['image_version'], {
            'usr/lib/test': str(number).encode(), 'etc/mu300/release.json': json.dumps(meta).encode(),
            'lib/apk/db/installed': b'P:example\nV:1\nA:aarch64\nD:libc\n\n'}, boot=boot)
        return release

    def zip(self, release):
        output = release.with_suffix('.zip')
        with zipfile.ZipFile(output, 'w') as z:
            for p in release.rglob('*'):
                if p.is_file(): z.write(p, 'nested/package/'+p.relative_to(release).as_posix())
        return output

    def test_full_zip_and_directory_match_existing_diff_studio(self):
        release = self.fixture()
        with Release(release) as old: expected = snapshot(old)
        self.assertEqual(tool.summarize(release), expected)
        self.assertEqual(tool.summarize(self.zip(release)), expected)

    def test_raw_tar_metadata_and_automatic_or_explicit_boot(self):
        release = self.fixture(); raw = release/'payload/mu300-openwrt.tar.gz'
        self.assertNotEqual(tool.summarize(raw)['release']['boot_digest'], tool.UNKNOWN_BOOT)
        boot = release/'payload/boot-linux.img'; other = self.root/'rootfs.gz'; shutil.copyfile(raw, other)
        self.assertEqual(tool.summarize(other)['release']['boot_digest'], tool.UNKNOWN_BOOT)
        self.assertEqual(tool.summarize(other, boot), tool.summarize(release))

    def test_saved_summary_can_replace_deleted_old_package(self):
        old, new = self.fixture(), self.fixture(2)
        expected = analyze(old, new)
        index = self.root/'old.json'; write_index(index, tool.summarize(old)); shutil.rmtree(old)
        result = analyze(index, new, self.root/'update.ota')
        self.assertEqual(result['manifest'], expected['manifest'])
        self.assertEqual(result['payload_bytes'], expected['payload_bytes'])

    def test_rootfs_without_boot_is_accepted_and_includes_target_boot(self):
        old, new = self.fixture(), self.fixture(2)
        raw = self.root/'rootfs.tar.gz'; shutil.copyfile(old/'payload/mu300-openwrt.tar.gz', raw)
        index = self.root/'raw.json'; write_index(index, tool.summarize(raw))
        result = analyze(index, new)
        self.assertEqual(result['manifest']['boot']['size'], 4)

    def test_corrupted_full_zip_is_rejected_before_output(self):
        old = self.fixture(); (old/'payload/boot-linux.img').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'): tool.summarize(self.zip(old))

    def test_tar_links_modes_xattrs_and_package_database_match(self):
        old = self.fixture(); raw = old/'payload/mu300-openwrt.tar.gz'
        with tarfile.open(raw, 'r:gz') as stream:
            nodes = [(n, stream.extractfile(n).read() if n.isfile() else None) for n in stream]
        with tarfile.open(raw, 'w:gz', format=tarfile.PAX_FORMAT) as stream:
            for n, data in nodes: stream.addfile(n, io.BytesIO(data) if data is not None else None)
            n = tarfile.TarInfo('usr/lib/link'); n.type=tarfile.SYMTYPE; n.linkname='test'; n.mode=0o777; stream.addfile(n)
            n = tarfile.TarInfo('usr/lib/hard'); n.type=tarfile.LNKTYPE; n.linkname='usr/lib/test'; stream.addfile(n)
            n = tarfile.TarInfo('usr/lib/mode'); n.mode=0o4755; n.uid=123; n.gid=456; n.size=3
            n.pax_headers={'SCHILY.xattr.user.example':'value'}; stream.addfile(n, io.BytesIO(b'abc'))
        import hashlib
        manifest = old/'desktop/manifest.json'; data=json.loads(manifest.read_text()); data['magisk']['payload/mu300-openwrt.tar.gz']=hashlib.sha256(raw.read_bytes()).hexdigest();manifest.write_text(json.dumps(data))
        with Release(old) as release: expected=snapshot(release)
        self.assertEqual(tool.summarize(old),expected)

    def test_missing_metadata_unsafe_paths_duplicates_and_garbage_rejected(self):
        raw = self.root/'bad.tar'
        for names in (['usr/a'], ['../a'], ['usr/a','usr/a']):
            with tarfile.open(raw, 'w') as stream:
                for name in names:
                    n=tarfile.TarInfo(name);n.size=1;stream.addfile(n,io.BytesIO(b'x'))
            with self.subTest(names=names), self.assertRaises(ValueError):tool.summarize(raw)
        raw.write_bytes(b'not a rootfs')
        with self.assertRaises(tarfile.TarError):tool.summarize(raw)

    def test_cli_unicode_spaces_output_and_idempotent_repeat(self):
        old=self.fixture(); release=self.zip(old); folder=self.root/'摘要 文件';folder.mkdir(); output=folder/'v1.json'
        command=[sys.executable,str(TOOL),str(release),'-o',str(output),'--no-pause']
        first=subprocess.run(command,capture_output=True,text=True,encoding='utf-8');self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        self.assertEqual(read_index(output),tool.summarize(old))
        second=subprocess.run(command,capture_output=True,text=True,encoding='utf-8');self.assertEqual(second.returncode,0)
        output.write_text('unrelated user file')
        failed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8');self.assertNotEqual(failed.returncode,0)
        self.assertEqual(output.read_text(),'unrelated user file');self.assertNotIn('Traceback',failed.stderr)

    def test_filename_includes_model_openwrt_kernel_and_source_identity(self):
        old=self.fixture(); data=tool.summarize(old);data['release']['meta']['image_version']='mu300-r20261026.123456-g12345678-sabcdef01'
        name=tool.filename(data)
        self.assertTrue(name.startswith('OpenWrt-index-mu300-25.12.5-k7.2.8-r20261026.123456-g12345678-'))
        self.assertTrue(name.endswith('.owrt-index.json'))

    def test_batch_directory_including_nested_zip_and_unpacked_release(self):
        collection=self.root/'data';collection.mkdir()
        a,b=self.fixture(),self.fixture(2)
        shutil.move(self.zip(a),collection/'old.zip')
        nested=collection/'nested';nested.mkdir();shutil.move(b,nested/'unpacked')
        (nested/'boot.img').write_bytes(b'not a rootfs')
        (collection/'readme.txt').write_text('ignored')
        result=subprocess.run([sys.executable,str(TOOL),str(collection),'--no-pause'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('2 inputs',result.stdout)
        self.assertIn('2 succeeded, 0 failed',result.stdout)
        indexes=list(collection.rglob('*.owrt-index.json'));self.assertEqual(len(indexes),2)
        self.assertEqual({read_index(p)['release']['meta']['image_version'] for p in indexes},{'mu300-r1','mu300-r2'})
        self.assertFalse(list((nested/'unpacked').rglob('*.owrt-index.json')))

    def test_batch_continues_after_bad_zip_and_reports_failure(self):
        collection=self.root/'data';collection.mkdir()
        (collection/'00-bad.zip').write_bytes(b'corrupt package')
        shutil.move(self.zip(self.fixture()),collection/'valid.zip')
        result=subprocess.run([sys.executable,str(TOOL),str(collection),'--no-pause'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,1)
        self.assertIn('1 succeeded, 1 failed',result.stdout)
        self.assertEqual(len(list(collection.glob('*.owrt-index.json'))),1)
        self.assertNotIn('Traceback',result.stderr)

    def test_batch_output_folder_and_repeated_run_reuses_existing(self):
        collection=self.root/'data';collection.mkdir()
        for release in (self.fixture(),self.fixture(2)):
            shutil.move(self.zip(release),collection/(release.name+'.zip'))
        output=self.root/'摘要 文件'
        command=[sys.executable,str(TOOL),str(collection),'-o',str(output),'--no-pause']
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        indexes=list(output.glob('*.owrt-index.json'));self.assertEqual(len(indexes),2)
        original={p:p.stat().st_mtime_ns for p in indexes}
        again=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(again.returncode,0);self.assertEqual(again.stdout.count('REUSED:'),2)
        self.assertEqual(original,{p:p.stat().st_mtime_ns for p in indexes})
        self.assertFalse(list(collection.glob('*.json')))

    def test_complete_release_directory_is_one_input_not_payload_batch(self):
        release=self.fixture()
        result=subprocess.run([sys.executable,str(TOOL),str(release),'--no-pause'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('[1/1]',result.stdout);self.assertNotIn('Batch:',result.stdout)
        self.assertEqual(len(list(self.root.glob('*.owrt-index.json'))),1)

    def test_empty_batch_and_ambiguous_options_fail_without_output(self):
        collection=self.root/'empty';collection.mkdir()
        for extra in ([],['--boot',str(self.root/'boot.img')],['-o',str(self.root/'output.json')]):
            result=subprocess.run([sys.executable,str(TOOL),str(collection),*extra,'--no-pause'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertNotIn('Traceback',result.stderr)
        self.assertFalse(list(self.root.rglob('*.json')))

    def test_malformed_rootfs_identity_is_reported_without_traceback(self):
        source=self.root/'bad.tar'
        with tarfile.open(source,'w') as stream:
            node=tarfile.TarInfo('etc/mu300/release.json');node.size=2;stream.addfile(node,io.BytesIO(b'[]'))
        result=subprocess.run([sys.executable,str(TOOL),str(source),'--no-pause'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,1);self.assertNotIn('Traceback',result.stderr)
        self.assertIn('Invalid release identity',result.stderr)

    def test_parallel_workers_really_overlap(self):
        collection=self.root/'data';collection.mkdir()
        for release in (self.fixture(),self.fixture(2)):
            shutil.move(self.zip(release),collection/(release.name+'.zip'))
        summarize=tool.summarize;barrier=threading.Barrier(2)
        started=[];lock=threading.Lock()
        def concurrent(*args,**kwargs):
            with lock:started.append(threading.get_ident())
            barrier.wait(timeout=5)
            return summarize(*args,**kwargs)
        with patch.object(tool,'summarize',side_effect=concurrent),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            result=tool.main([str(collection),'--jobs','2','--no-pause'])
        self.assertEqual(result,0);self.assertEqual(len(set(started)),2)
        self.assertEqual(len(list(collection.glob('*.owrt-index.json'))),2)

    def test_parallel_same_output_reuses_identical_data_without_overwrite(self):
        collection=self.root/'data';collection.mkdir();release=self.zip(self.fixture())
        for name in ('a.zip','b.zip'):shutil.copyfile(release,collection/name)
        summarize=tool.summarize;barrier=threading.Barrier(2);output=io.StringIO()
        def concurrent(*args,**kwargs):
            data=summarize(*args,**kwargs);barrier.wait(timeout=5);return data
        with patch.object(tool,'summarize',side_effect=concurrent),redirect_stdout(output),redirect_stderr(io.StringIO()):
            result=tool.main([str(collection),'--jobs','2','--no-pause'])
        self.assertEqual(result,0);self.assertEqual(output.getvalue().count('REUSED:'),1)
        self.assertEqual(len(list(collection.glob('*.owrt-index.json'))),1)

    def test_parallel_conflicting_output_preserves_first_successful_summary(self):
        collection=self.root/'data';collection.mkdir();a,b=self.fixture(),self.fixture(2)
        meta=b/'desktop/release.json';data=json.loads(meta.read_text());data['image_version']='mu300-r1';meta.write_text(json.dumps(data))
        for release in (a,b):shutil.move(self.zip(release),collection/(release.name+'.zip'))
        summarize=tool.summarize;write=tool.write_index;barrier=threading.Barrier(2);saved=[];output=io.StringIO()
        def concurrent(*args,**kwargs):
            data=summarize(*args,**kwargs);barrier.wait(timeout=5);return data
        def record(path,data,**kwargs):
            result=write(path,data,**kwargs);saved.append(data);return result
        with patch.object(tool,'summarize',side_effect=concurrent),patch.object(tool,'write_index',side_effect=record),redirect_stdout(output),redirect_stderr(io.StringIO()):
            result=tool.main([str(collection),'--jobs','2','--no-pause'])
        self.assertEqual(result,1);self.assertIn('1 succeeded, 1 failed',output.getvalue())
        self.assertEqual(len(saved),1)
        index=next(collection.glob('*.owrt-index.json'));self.assertEqual(read_index(index),saved[0])

    def test_parallel_and_serial_indexes_match_and_jobs_must_be_positive(self):
        collection=self.root/'data';collection.mkdir()
        for release in (self.fixture(),self.fixture(2)):
            shutil.move(self.zip(release),collection/(release.name+'.zip'))
        for jobs in ('1','4'):
            result=subprocess.run([sys.executable,str(TOOL),str(collection),'-o',str(self.root/jobs),'--jobs',jobs,'--no-pause'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        serial={p.name:p.read_bytes() for p in (self.root/'1').glob('*.json')}
        parallel={p.name:p.read_bytes() for p in (self.root/'4').glob('*.json')};self.assertEqual(serial,parallel)
        for jobs in ('0','-2','abc'):
            result=subprocess.run([sys.executable,str(TOOL),str(collection),'--jobs',jobs,'--no-pause'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,2);self.assertNotIn('Traceback',result.stderr)

    def test_interrupt_cancels_running_and_queued_jobs_without_writes(self):
        collection=self.root/'data';collection.mkdir();release=self.zip(self.fixture())
        for name in ('a.zip','b.zip','queued.zip'):shutil.copyfile(release,collection/name)
        barrier=threading.Barrier(3);attempted=[]
        def running(source,boot,progress):
            attempted.append(source);barrier.wait(timeout=5)
            while True:
                progress(1,'usr/lib/test')
                threading.Event().wait(.01)
        def interrupt(*args,**kwargs):
            barrier.wait(timeout=5);raise KeyboardInterrupt()
        with patch.object(tool,'summarize',side_effect=running),patch.object(tool,'wait',side_effect=interrupt),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            result=tool.main([str(collection),'--jobs','2','--no-pause'])
        self.assertEqual(result,130);self.assertEqual(len(attempted),2)
        self.assertFalse(list(collection.glob('*.json')))

    @unittest.skipUnless(shutil.which('mke2fs'), 'Tiny ext4 fixture needs Linux mke2fs')
    def test_raw_and_gz_ext4_and_e5_zip_match_existing_reader(self):
        root=self.root/'root';(root/'etc/e5').mkdir(parents=True);(root/'usr/lib').mkdir(parents=True)
        meta=dict(profile='e5',image_version='e5-r1',kernel_release='6.18.54',openwrt='25.12.5')
        (root/'etc/e5/release.json').write_text(json.dumps(meta));(root/'usr/lib/test').write_bytes(b'payload')
        (root/'usr/lib/link').symlink_to('test');image=self.root/'root.ext4'
        subprocess.run(['mke2fs','-q','-t','ext4','-F','-d',str(root),str(image),'16M'],check=True,capture_output=True)
        raw=tool.summarize(image)
        compressed=self.root/'root.ext4.gz'
        with image.open('rb') as src,gzip.open(compressed,'wb') as dest:shutil.copyfileobj(src,dest)
        self.assertEqual(raw,tool.summarize(compressed))
        release=self.root/'e5';files=release/'files';files.mkdir(parents=True);shutil.copyfile(compressed,files/'openwrt.ext4.gz')
        (files/'boot.img').write_bytes(b'boot');(files/'RELEASE.json').write_text(json.dumps(meta));(files/'device-profile.json').write_text('{"profile":"e5"}')
        import hashlib
        (files/'SHA256SUMS').write_text(''.join(hashlib.sha256((files/n).read_bytes()).hexdigest()+'  files/'+n+'\n' for n in ('openwrt.ext4.gz','boot.img')))
        with Release(release) as release_reader:expected=snapshot(release_reader)
        self.assertEqual(tool.summarize(release),expected)
        self.assertEqual(tool.summarize(self.zip(release)),expected)
        self.assertEqual(tool.summarize(image,files/'boot.img'),expected)


if __name__=='__main__':unittest.main()
