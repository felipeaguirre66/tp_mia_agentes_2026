# Manifest de resultados M3

- Timestamp UTC: 20260822T225250Z
- Proveedor: `ollama`
- Modelo: `qwen3.6`
- Ollama: `0.31.1`
- Git SHA experimental: `210eb1fbbc52c20e90dbaccec6eb66b3f5890c53`
- Python: `3.14.0` (Windows)
- Casos: 120

## Comandos

```bash
PYTHON_BIN='/mnt/c/Program Files/Python314/python.exe' REPEATS=3 bash eval/run_all.sh
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --scenarios easy,medium --repeats 3 --out results/final-20260822T225250Z/baseline-a.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --scenarios hard --repeats 3 --out results/final-20260822T225250Z/baseline-b.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --scenarios extreme --repeats 3 --timeout 600 --out results/final-20260822T225250Z/baseline-c.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --config prompt_baseline --scenarios medium,hard --repeats 3 --out results/final-20260822T225250Z/exp-a.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --config mem_6,mem_20 --scenarios medium,hard --repeats 3 --out results/final-20260822T225250Z/exp-b.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --config noop_examine,iters_10,iters_20 --scenarios medium,hard --repeats 3 --out results/final-20260822T225250Z/exp-c.jsonl
'/mnt/c/Program Files/Python314/python.exe' eval/run.py --config repair_off --scenarios all --repeats 3 --timeout 600 --out results/final-20260822T225250Z/exp-d.jsonl
```

## Archivos

| archivo | bytes | SHA-256 |
|---|---:|---|
| `baseline-a.jsonl` | 53471 | `e1dcac590f5a63601c42e77c9f22dd32d3fb6161b003f9bbaace23d00d05410a` |
| `baseline-b.jsonl` | 109652 | `697f6ba775ebf5d12082ad65058cfb6957f7c5d0e6e281c12f5b46da781af375` |
| `baseline-c.jsonl` | 117320 | `25f70fabf13e38cee1e192e16ea78f41a390cd9260bfb3b8f49284ff0ba78868` |
| `exp-a.jsonl` | 93884 | `1e8547535948070f7831c5cc826c095aa6dbc9e97fb8bd24941e3cda73971cf1` |
| `exp-b.jsonl` | 302468 | `4ff084c49e6143c1ec8faf850e007f0076a29094c8b1961baaf7e345d7e8c322` |
| `exp-c.jsonl` | 295654 | `a08afed21115b67b5ea20a2b7a9549dc2d3e62142161b9c137ca62dce5f83fd2` |
| `exp-d.jsonl` | 270392 | `ab22e2e8f5d1b5fc173ec3120aea2d9616c87809b89b2da98835275c29890d97` |
