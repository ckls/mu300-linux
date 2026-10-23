// No subprocess, AT access, arbitrary path, or caller-selected interface.
'use strict';
import { sample } from 'mu300.rates';
return { mu300rates: { rates: { call: function() { return sample(); } } } };
