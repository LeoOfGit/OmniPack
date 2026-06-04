import inspect
try:
    from winpty import PtyProcess
    print(inspect.signature(PtyProcess.spawn))
except Exception as e:
    print("Error:", e)
