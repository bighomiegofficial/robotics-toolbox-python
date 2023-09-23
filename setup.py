from setuptools import setup, Extension
import os
import numpy
# fmt: on

here = os.path.abspath(os.path.dirname(__file__))

req = [
    "numpy>=1.17.4",
    "spatialmath-python~=1.0.0",
    "spatialgeometry~=1.0.0",
    "pgraph-python",
    "scipy",
    "matplotlib",
    "ansitable",
    # "swift-sim~=1.0.0",
    "rtb-data",
    "progress",
]

collision_req = ["pybullet"]

vp_req = ["vpython", "numpy-stl", "imageio", "imageio-ffmpeg"]

dev_req = ["pytest", "pytest-cov", "flake8", "pyyaml", "sympy"]

docs_req = [
    "sphinx",
    "sphinx_rtd_theme",
    "sphinx-autorun",
]

# Get the long description from the README file
with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

# list all data folders here, to ensure they get packaged

extra_folders = [
    "roboticstoolbox/core",
]


def package_files(directory):
    paths = []
    for (pathhere, _, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append(os.path.join("..", pathhere, filename))
    return paths


extra_files = []
for extra_folder in extra_folders:
    extra_files += package_files(extra_folder)

frne = Extension(
    "roboticstoolbox.frne",
    sources=[
        "./roboticstoolbox/core/vmath.c",
        "./roboticstoolbox/core/ne.c",
        "./roboticstoolbox/core/frne.c",
    ],
    include_dirs=["./roboticstoolbox/core/"],
)

fknm = Extension(
    "roboticstoolbox.fknm",
    sources=[
        "./roboticstoolbox/core/methods.cpp",
        "./roboticstoolbox/core/ik.cpp",
        "./roboticstoolbox/core/linalg.cpp",
        "./roboticstoolbox/core/fknm.cpp",
    ],
    include_dirs=["./roboticstoolbox/core/", numpy.get_include()],
)

setup(
    ext_modules=[frne, fknm],
    package_data={"roboticstoolbox": extra_files},
)
