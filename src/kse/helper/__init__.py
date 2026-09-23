"""Files installed as root by `kse helper install`: the wake-alarm helper and polkit files.

kse_helper_linux.py runs with the system Python as root: standard library only, and it
must never import kse.
"""
