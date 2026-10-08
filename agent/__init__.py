"""Financial Agent Runtime package.

Keeping ``agent`` as an explicit package prevents a sibling test package named
``tests.agent`` from shadowing production modules in spawned worker processes.
"""

from .__version__ import BASE_VERSION, __version__

__all__ = ["BASE_VERSION", "__version__"]
