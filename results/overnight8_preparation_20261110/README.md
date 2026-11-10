# Overnight8 preparation — 10–11 November2026

Prepared and started, not a completed-results report. **24scientific runs** were
admitted: full CIFAR-10,20logical clients,ring,IID/Dirichlet0.5,CNN/MLP,
baseline/adaptive,seeds1/2/3,60rounds. Conservative projection:
**4.49h**, already2x measured stages.
The1h reserve and calibration are inside the8h wall limit.
Start:2026-11-10T22:03:13.456338+00:00; deadline:2026-11-11T06:03:13.456338+00:00.
Pause/resume never resets it. Current counters are in the live CLI, not this
historical export snapshot. No completed overnight accuracy claim is made.

The references folder contains24verified completed20round receipts and metrics
from the prior144run laptop series. They are cost/reference evidence, not new
60round runs. Max-seed per-stage projections keep the same model/mode/split,
GPU/driver/cache/source and account for60rounds plus12validation checks.
The four alpha0.1 seed0/two-round calibrations passed; its12scientific runs were
excluded by the conservative budget. Their scores are not thesis measurements.

Seven new unit/control tests and an actual Windows venv child-process-tree
termination gate passed. This gate used a sleeping process, not training or
another user's process. The deadline watcher kills its own training subtree.
Checkpointed pause remains available. The temporary system-awake helper keeps
only system idle sleep inhibited while this controller lives or until deadline;
the display may sleep and permanent power settings are unchanged.

Training starts fresh with a60round cosine schedule, not a20round checkpoint
extension.20vs60comparisons change horizon AND schedule; within the new same
trajectory, validation20/40/60shows continued convergence. Test scores are not
used to choose seeds, modes or budget admission. Full three-seed groups alone
receive mean/sampleSD. The trainer holds plaintexts/private CKKS keys; privacy
from that trainer and measured WAN traffic are not claimed.

Original144/402/228runs, server source and separate isolated/proved protocol are
preserved. No Word/PowerPoint/dashboard has been replaced with partial results.
See docs/OVERNIGHT8_EL.md and the source-frozen pack for explicit commands.
Datasets/checkpoints/CKKS keys/credentials are excluded from publication.
