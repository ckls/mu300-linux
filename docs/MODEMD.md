# Native OpenWrt services

The C bridge and ucode modem/system service cores originate from
liuwang97/mu300-linux `ccf89bb65e283f1c609f507f4c51585b929b6e99`
(cpu-load), adapted to this branch's channel layout and policies.

OpenWrt has one implementation per migrated operation. It requires the packaged
native helpers and ucode modules; missing dependencies are reported as errors.
There is no old-image probe, automatic backend selection, disable-marker mode,
or alternate worker launched after an RPC failure. Ubuntu retains its original
platform services. This is an explicit platform boundary, not a recovery path.

* `mu300-atd-io` owns SIPC descriptors; `mu300-modemd` can restart without
  closing them. CLI/FIFO clients retain their interfaces. The init service
  rejects an existing physical owner instead of hot-switching to another one.
  Model layouts preserve NR6/7, NR3 ownership and U30 sbuf/no-reopen rules.
* Background LuCI cell refresh calls `mu300.modem.collect` with explicit string
  slot `0`/`1` and mode `full`/`fast`. SIM1 uses NR4 and its own cache/identity
  directory. The original 1/5-second TTLs and staged output remain. The existing
  synchronous live-signal CLI remains the implementation of the separate
  `signal` operation; it is never selected as a replacement for failed native
  background collection. The complete system snapshot still uses the original
  `dashboard-info` until that operation is fully rewritten.
* The rates page calls only `mu300rates.rates` in rpcd. The `dashboard-rates`
  CLI imports the same sampler. WAN selection, counters, ifindex, boot ID and
  monotonic timestamp remain; plugin permissions are fixed during installation.
* OpenWrt `mu300-sysd` replaces its old buttons/thermal service entries. Local
  button actions, U30 double-click, five-second checks, vendor cooling policy,
  owned frequency caps and mainline emergency shutdown remain. Ubuntu still
  runs its original buttons/thermal services.
* OpenWrt SMS init explicitly sets `MU300_SMS_TRANSPORT=ubus`; Ubuntu uses its
  existing `urc-log` transport. A lost ubus listener is an error, never a switch
  to log polling. Physical SIM filtering, spool/import/ACK, five-second failed
  import retry and 300-second archive checks remain. PDU contents are not logged
  or included in events. Stock CNMI rejection/ACK recovery is retained.
* OpenWrt data watch requires ubus events and retains the original recovery
  decisions and 30-second safety interval. User data-off, switching gates,
  active-SIM resolution, in-place renew and two confirmed detach observations
  remain. Listener/service loss fails the task for normal procd supervision.
* NDP requires ip-full and its event/SIM-mapping libraries. Stable kernel
  snapshots absorb self-generated notifications; concurrent addresses and
  deletions trigger a new pass. Ten-second checks, neighbour pins, metrics and
  paced withdrawal RAs remain. Missing tables or monitor loss are errors.

No device/boot-time/current measurement is implied by the automated tests.

Build the ARM64 static helper into the registered input directory using:

```sh
python3 tools/build-release.py run --label atd-io -- sh tools/atd-io/build.sh /path/to/registered/inputs/tools/atd-io
```

The builder requires an installed AArch64 compiler (or an explicit `CC`). Missing
compilers fail the build; the script does not select another environment. Source/binary hashes and ELF checks reject a stale,
wrong-architecture or dynamically linked helper during release checks. Both
rootfs assemblers copy the helper; OpenWrt also installs the ucode modules.
No desktop installer payload changes are required.

## The bridge protocol (mu300-atd-io <-> its client)

A unix stream socket, `-s PATH` (default `/run/mu300-modem/io.sock`), mode 0600 in a 0700 directory. One client at a
time: a new connection replaces the old one (a restarted modemd is never locked out by a stale connection). Records
are lines of printable ASCII ending in `\n`, fields separated by one space; payloads are uppercase hex (`2B43...`),
so nothing a modem or a client sends can break the framing. Channel names are `[a-z0-9_-]{1,16}`.

Client to bridge:

| record | meaning |
|---|---|
| `OPEN NAME DEVICE [READY]` | own DEVICE as channel NAME: open it (O_RDWR, O_NOCTTY, O_NONBLOCK; raw termios where it is a tty) now, else try again every 200 ms until it opens or the channel is CLOSEd. READY is optional, `sbuf:SBUF`: before each attempt the line `SBUF, state: 1,` must be in `/dev/sipc_sbuf` (the second SIM group's channels have a node before the modem side is up, FINDINGS 186). Repeating an OPEN for a channel that exists with the same device changes nothing and answers its STATE. |
| `FIFO NAME PATH` | own the request FIFO of channel NAME: create PATH (mode 0600; an existing FIFO is reused, anything else is replaced), open it O_RDWR and O_NONBLOCK, and forward its complete lines. Repeats change nothing. |
| `TX NAME HEX` | write the bytes to the channel, all of them (waiting up to 2 s for it to take them). |
| `REOPEN NAME` | close the channel's descriptor and open the device again (then the OPEN retry rule). |
| `CLOSE NAME` | close and forget the channel or FIFO NAME. |
| `PING TOKEN` | answered with `PONG TOKEN`. |

Bridge to client:

| record | meaning |
|---|---|
| `HELLO VERSION PID` | the first record of every connection (VERSION is 1) |
| `STATE NAME DEVICE STATE` | after HELLO for every channel and FIFO it holds, and on every change: `open`, `pending`, `eof`, `closed` |
| `OPENFAIL NAME ERRNO` | the first failed attempt of a pending open (one per pending period) |
| `RX NAME HEX` | one line from the channel: the bytes before `\n`, one trailing `\r` removed; empty lines too. A line longer than 8192 bytes goes out in 8192-byte pieces. |
| `RXP NAME HEX` | bytes without a newline that have waited 300 ms (a prompt such as `> `) |
| `REQ NAME HEX` | one complete line from the channel's FIFO, without its `\n` |
| `TXERR NAME ERRNO` | a TX that could not be written whole |
| `EOF NAME` | a terminal read 0 bytes or failed (a pty whose other side closed): the descriptor is closed and the channel is `eof`; it is not reopened by itself. A SIPC channel is not a terminal and never sends this: nothing to read (EAGAIN, ENODATA, EBUSY) is just that, and any other error, a read of 0 bytes or a hangup keeps it open and out of the poll for 1 s, since closing it would silence it until a reboot |
| `DROPPED NAME COUNT` | records that did not fit the queue while no client was connected |
| `PONG TOKEN` | |

While no client is connected the bridge keeps reading every channel (an unread SIPC ring only fills up) and queues
RX/RXP/REQ/STATE records, 1024 per channel and 256 KiB in all, the oldest dropped first; they follow HELLO and the
STATE lines on the next connection. The bridge never exits because of its client; SIGTERM closes everything and ends
it. It does not fork into the background (procd supervises it).

## modemd

* Brokers: the channel layout `mu300-atd`'s init script chose (`start_single_sim`: atd on nr1 with nr0's URCs, atd2 on nr2, additional nr3–7 per local policy;
  `start_sim2`: atd/atd2/atd4/atd5 on nr1/nr2/nr4/nr5 with the URCs of nr0 and nr3, no reopen, the sbuf condition)
  is handed to modemd as one argument per broker; the init script keeps every other decision (the SIM slot, the
  dual-SIM fallbacks, the warm-up instances).
* Per broker: `$DIR/cmd` (the FIFO, via the bridge), `$DIR/owner/pid` (the bridge's pid, whose command line has
  `mu300-atd`), `$DIR/urc/*.log` (capped at MU300_AT_URC_MAX, 64 KiB), and the request rule of `mu300-at`: the line
  `T ANSWER-FILE COMMAND`, the answer file `$DIR/answer.<pid>` written whole (`.part`, then renamed), and the same
  checks (`one_request`, the timeout range, the answer file's name).
* A command: drain first (quiet for 0.05 s after a clean reply, for 1 s otherwise; at most 3 s, 25 s after an
  unanswered command), write it with `\r`, collect until a final result code (`OK`, `ERROR`, `+CME ERROR`, `+CMS ERROR`,
  `CONNECT`, `NO CARRIER`) or T + 1 s. Lines in a drain go to the channel's own URC log (never the command's echo,
  which can hold a secret). `+CMT:` frames go to `mu300-cmt-spool` on its stdin, never into a reply or a log.
* URC channels: every line to its log, validated `+ECIND` to `mu300.sim-change`, CEREG/scoped replies to the native passive cache, and a ubus event
  `mu300.modem.urc` (`{ "channel": "nr0", "line": "..." }`; `+CMT` frames and lines that can carry a secret are not
  sent).
* The reopen rule: five unanswered commands in a row, the last reopen more than 300 s ago, and the live URC log quiet
  for 240 s; never with MU300_AT_DISABLE_REOPEN.
* ubus `mu300.modem`: `at { cmd, timeout, channel }` (answered when the reply is in), `status`, `cell { mode }`
  (start a collection round now unless one is running or the cache is fresh; answers at once), `urc` events.
* The panel's collection (`unisoc-modem/cell`'s rounds) runs inside modemd when the status plugin asks for it, with
  the same commands, files and JSON, without a process per round.


## Resident dashboard and service placement

OpenWrt's LuCI readers use `mu300status.status/cells/sysinfo/sms_head`,
`mu300rates.rates` and `mu300.modem.signal`. Read ACLs expose only those fixed
methods, not arbitrary AT access. Missing native objects produce an error; no
RPC/backend probing starts an old worker. The compatibility RPC and
`dashboard-info` CLI use the same implementations.

`mu300.dash` imports the existing public APN and hotspot modules. It reads
procfs/sysfs, UCI, netlink and bounded ubus replies directly, without shell
subprocesses. SMS notifications read a per-SIM pool signature first; message
lists are read only after a change. Explicitly configured external SMS adapters
retain their own list polling; their storage format is never guessed. This does not change SMS import/ACK policy.

Live signal requests use private rounds inside modemd and never overwrite the
background caches. The existing physical-channel pool and SIM switch/epoch
checks apply. A live reply has a 12-second deadline. If an AT read is already
queued, a timed-out caller receives an error while that round retains its pool
until the pending read finishes; it cannot free a channel into overlapping work.

`mu300-service-cpus` is an OpenWrt one-shot service. Its `little` setting places
procd services on online CPUs of the lowest reported capacity. `all` removes
that cpuset restriction. Run `mu300-service-cpus all` or
`mu300-service-cpus little` as root to apply and save the choice;
`mu300-service-cpus get` reports it. The setting is stored in
`unisoc_modem.main.services_cpus`. It changes no CPU online state, frequency,
voltage, interrupts or charging policy. Unsupported/missing cgroup requirements
are reported as errors.


Native collector/client locks identify the current process directly and split
other processes' NUL-separated argv before checking ownership. A native request
holds its client lock until completion: a wall-clock deadline from the CLI lock
format must never reclaim or kill a live modemd owner, including another daemon.
