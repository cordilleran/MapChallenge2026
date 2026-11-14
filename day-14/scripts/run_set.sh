#!/bin/sh
set -u
# Day 14 run set: base run, grid-size test, equifinality sweep. Single-threaded maths (12x faster here).
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cd "$(dirname "$0")/.." || exit 1
PY=${PY:-python3}          # the Day 10 environment (day-10/requirements.txt), e.g. PY=../day-10/.venv/bin/python
mkdir -p runs/sweep
# 19 runs at once: about 19 cores; the 1 mm run sets the wall time (about 45 min)
BASE=""   # the sim.py defaults are the published base run
$PY -I sim.py --out runs/base_2mm --dx 0.002 $BASE > runs/base_2mm.log 2>&1 &
$PY -I sim.py --out runs/grid_1mm --dx 0.001 $BASE --film-smooth 3.0 > runs/grid_1mm.log 2>&1 &
$PY -I sim.py --out runs/grid_4mm --dx 0.004 $BASE --film-smooth 0.75 > runs/grid_4mm.log 2>&1 &
for K in 1e-3 2e-3 4e-3 8e-3; do for KR in 1.25e2 2.5e2 5e2 1e3; do
  $PY -I sim.py --out runs/sweep/K${K}_Kr${KR} --dx 0.004 --film-smooth 0.75 --stage 0.012 --K $K --tauc 0.06 --Kr $KR --theta 1e-9 --film 3e-4 --rough 0.05 --tmax 120 --stop-frac 0.01 > /dev/null 2>&1 &
done; done
wait
echo RUNSET-DONE
