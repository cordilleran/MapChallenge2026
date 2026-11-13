# Evaluation image: runs each candidate sim.py with no network, as a non-root user.
# Same versions as the Python environment the agents were given to develop against.
FROM python:3.14-slim
RUN pip install --no-cache-dir numpy==2.3.5 scipy==1.16.3 matplotlib==3.10.7
# One CPU means one thread: --cpus limits time, not the thread count numpy sees (fair timing).
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    MPLCONFIGDIR=/opt/mpl
# Build matplotlib's font cache once, writable by any user (throwaway container), so no run pays for it.
RUN mkdir -p /opt/mpl && python -c "import matplotlib.font_manager" && chmod -R a+rwX /opt/mpl
WORKDIR /work
