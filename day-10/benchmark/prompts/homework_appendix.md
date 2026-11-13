
## Show your homework

This run is part of a benchmark, and your working will be checked by other tests after you finish. Keep a record as you go, and at the end package everything as one file, `submission.zip`, that the user can download. Do not tidy away failed attempts: they are part of the record.

`submission.zip` must contain exactly this layout:

```
submission/
  sim.py                       the final script
  run42/                       the OUTDIR from: python3 sim.py --seed 42 --out run42
  homework/
    environment.txt            output of: python3 -V; python3 -c "import numpy, scipy, matplotlib; print(numpy.__version__, scipy.__version__, matplotlib.__version__)"; uname -a
    commands.log               every command you ran, in order: the command, its exit code, its run time, and the last 20 lines of its output
    attempts.md                each version of sim.py you ran, numbered: what you changed, what happened, why you changed it next
    assumptions.md             the assumptions table from your reply
    self_checks.md             any checks you ran on your own results (mass balance, stability, the same seed twice), with their output
    versions/                  every earlier version of sim.py, named attempt_01.py, attempt_02.py, ...
```

If you cannot run Python here, say so at the top of `homework/attempts.md`, still deliver `sim.py`, leave out `run42/`, and say which parts of the record are therefore missing. If you cannot make a zip file, give the same files and folders in your reply instead, one code block each, headed with their path.
