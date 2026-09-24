"""Files installed as root by `powerclock helper install`: the wake-alarm helper and polkit files.

powerclock_helper_linux.py runs with the system Python as root: standard library only, and it
must never import powerclock.
"""
