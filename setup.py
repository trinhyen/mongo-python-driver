import os
import platform
import re
import sys
import warnings

# Hack to silence atexit traceback in some Python versions
try:
    import multiprocessing
except ImportError:
    pass

# Don't force people to install setuptools unless
# we have to.
try:
    from setuptools import setup
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup

from distutils.cmd import Command
from distutils.command.build_ext import build_ext
from distutils.errors import CCompilerError, DistutilsOptionError
from distutils.errors import DistutilsPlatformError, DistutilsExecError
from distutils.core import Extension

try:
    import sphinx
    _HAVE_SPHINX = True
except ImportError:
    _HAVE_SPHINX = False

version = "3.4rc1.dev0"

f = open("README.rst")
try:
    try:
        readme_content = f.read()
    except:
        readme_content = ""
finally:
    f.close()

# PYTHON-654 - Clang doesn't support -mno-fused-madd but the pythons Apple
# ships are built with it. This is a problem starting with Xcode 5.1
# since clang 3.4 errors out when it encounters unrecognized compiler
# flags. This hack removes -mno-fused-madd from the CFLAGS automatically
# generated by distutils for Apple provided pythons, allowing C extension
# builds to complete without error. The inspiration comes from older
# versions of distutils.sysconfig.get_config_vars.
if sys.platform == 'darwin' and 'clang' in platform.python_compiler().lower():
    from distutils.sysconfig import get_config_vars
    res = get_config_vars()
    for key in ('CFLAGS', 'PY_CFLAGS'):
        if key in res:
            flags = res[key]
            flags = re.sub('-mno-fused-madd', '', flags)
            res[key] = flags


class test(Command):
    description = "run the tests"

    user_options = [
        ("test-module=", "m", "Discover tests in specified module"),
        ("test-suite=", "s",
         "Test suite to run (e.g. 'some_module.test_suite')"),
        ("failfast", "f", "Stop running tests on first failure or error")
    ]

    def initialize_options(self):
        self.test_module = None
        self.test_suite = None
        self.failfast = False

    def finalize_options(self):
        if self.test_suite is None and self.test_module is None:
            self.test_module = 'test'
        elif self.test_module is not None and self.test_suite is not None:
            raise DistutilsOptionError(
                "You may specify a module or suite, but not both"
            )

    def run(self):
        # Installing required packages, running egg_info and build_ext are
        # part of normal operation for setuptools.command.test.test
        if self.distribution.install_requires:
            self.distribution.fetch_build_eggs(
                self.distribution.install_requires)
        if self.distribution.tests_require:
            self.distribution.fetch_build_eggs(self.distribution.tests_require)
        self.run_command('egg_info')
        build_ext_cmd = self.reinitialize_command('build_ext')
        build_ext_cmd.inplace = 1
        self.run_command('build_ext')

        # Construct a TextTestRunner directly from the unittest imported from
        # test (this will be unittest2 under Python 2.6), which creates a
        # TestResult that supports the 'addSkip' method. setuptools will by
        # default create a TextTestRunner that uses the old TestResult class,
        # resulting in DeprecationWarnings instead of skipping tests under 2.6.
        from test import unittest, PymongoTestRunner, test_cases
        if self.test_suite is None:
            all_tests = unittest.defaultTestLoader.discover(self.test_module)
            suite = unittest.TestSuite()
            suite.addTests(sorted(test_cases(all_tests),
                                  key=lambda x: x.__module__))
        else:
            suite = unittest.defaultTestLoader.loadTestsFromName(
                self.test_suite)
        result = PymongoTestRunner(verbosity=2,
                                   failfast=self.failfast).run(suite)
        sys.exit(not result.wasSuccessful())


class doc(Command):

    description = "generate or test documentation"

    user_options = [("test", "t",
                     "run doctests instead of generating documentation")]

    boolean_options = ["test"]

    def initialize_options(self):
        self.test = False

    def finalize_options(self):
        pass

    def run(self):

        if not _HAVE_SPHINX:
            raise RuntimeError(
                "You must install Sphinx to build or test the documentation.")

        if sys.version_info[0] >= 3:
            import doctest
            from doctest import OutputChecker as _OutputChecker

            # Match u or U (possibly followed by r or R), removing it.
            # r/R can follow u/U but not precede it. Don't match the
            # single character string 'u' or 'U'.
            _u_literal_re = re.compile(
                r"(\W|^)(?<![\'\"])[uU]([rR]?[\'\"])", re.UNICODE)
             # Match b or B (possibly followed by r or R), removing.
             # r/R can follow b/B but not precede it. Don't match the
             # single character string 'b' or 'B'.
            _b_literal_re = re.compile(
                r"(\W|^)(?<![\'\"])[bB]([rR]?[\'\"])", re.UNICODE)

            class _StringPrefixFixer(_OutputChecker):

                def check_output(self, want, got, optionflags):
                    if sys.version_info[0] >= 3:
                        # The docstrings are written with python 2.x in mind.
                        # To make the doctests pass in python 3 we have to
                        # strip the 'u' prefix from the expected results. The
                        # actual results won't have that prefix.
                        want = re.sub(_u_literal_re, r'\1\2', want)
                        # We also have to strip the 'b' prefix from the actual
                        # results since python 2.x expected results won't have
                        # that prefix.
                        got = re.sub(_b_literal_re, r'\1\2', got)
                    return super(
                        _StringPrefixFixer, self).check_output(
                            want, got, optionflags)

                def output_difference(self, example, got, optionflags):
                    if sys.version_info[0] >= 3:
                        example.want = re.sub(
                            _u_literal_re, r'\1\2', example.want)
                        got = re.sub(_b_literal_re, r'\1\2', got)
                    return super(
                        _StringPrefixFixer, self).output_difference(
                            example, got, optionflags)

            doctest.OutputChecker = _StringPrefixFixer

        if self.test:
            path = "doc/_build/doctest"
            mode = "doctest"
        else:
            path = "doc/_build/%s" % version
            mode = "html"

            try:
                os.makedirs(path)
            except:
                pass

        status = sphinx.main(["-E", "-b", mode, "doc", path])

        if status:
            raise RuntimeError("documentation step '%s' failed" % (mode,))

        sys.stdout.write("\nDocumentation step '%s' performed, results here:\n"
                         "   %s/\n" % (mode, path))


if sys.platform == 'win32' and sys.version_info > (2, 6):
    # 2.6's distutils.msvc9compiler can raise an IOError when failing to
    # find the compiler
    build_errors = (CCompilerError, DistutilsExecError,
                    DistutilsPlatformError, IOError)
else:
    build_errors = (CCompilerError, DistutilsExecError, DistutilsPlatformError)


class custom_build_ext(build_ext):
    """Allow C extension building to fail.

    The C extension speeds up BSON encoding, but is not essential.
    """

    warning_message = """
********************************************************************
WARNING: %s could not
be compiled. No C extensions are essential for PyMongo to run,
although they do result in significant speed improvements.
%s

Please see the installation docs for solutions to build issues:

http://api.mongodb.org/python/current/installation.html

Here are some hints for popular operating systems:

If you are seeing this message on Linux you probably need to
install GCC and/or the Python development package for your
version of Python.

Debian and Ubuntu users should issue the following command:

    $ sudo apt-get install build-essential python-dev

Users of Red Hat based distributions (RHEL, CentOS, Amazon Linux,
Oracle Linux, Fedora, etc.) should issue the following command:

    $ sudo yum install gcc python-devel

If you are seeing this message on Microsoft Windows please install
PyMongo using the MS Windows installer for your version of Python,
available on pypi here:

http://pypi.python.org/pypi/pymongo/#downloads

If you are seeing this message on OSX please read the documentation
here:

http://api.mongodb.org/python/current/installation.html#osx
********************************************************************
"""

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError:
            e = sys.exc_info()[1]
            sys.stdout.write('%s\n' % str(e))
            warnings.warn(self.warning_message % ("Extension modules",
                                                  "There was an issue with "
                                                  "your platform configuration"
                                                  " - see above."))

    def build_extension(self, ext):
        name = ext.name
        if sys.version_info[:3] >= (2, 6, 0):
            try:
                build_ext.build_extension(self, ext)
            except build_errors:
                e = sys.exc_info()[1]
                sys.stdout.write('%s\n' % str(e))
                warnings.warn(self.warning_message % ("The %s extension "
                                                      "module" % (name,),
                                                      "The output above "
                                                      "this warning shows how "
                                                      "the compilation "
                                                      "failed."))
        else:
            warnings.warn(self.warning_message % ("The %s extension "
                                                  "module" % (name,),
                                                  "PyMongo supports python "
                                                  ">= 2.6."))

ext_modules = [Extension('bson._cbson',
                         include_dirs=['bson'],
                         sources=['bson/_cbsonmodule.c',
                                  'bson/time64.c',
                                  'bson/buffer.c',
                                  'bson/encoding_helpers.c']),
               Extension('pymongo._cmessage',
                         include_dirs=['bson'],
                         sources=['pymongo/_cmessagemodule.c',
                                  'bson/buffer.c'])]

extras_require = {'tls': []}
vi = sys.version_info
if vi[0] == 2:
    extras_require['tls'].append("ipaddress")
if sys.platform == 'win32':
    extras_require['gssapi'] = ["winkerberos>=0.3.0"]
    if vi[0] == 2 and vi < (2, 7, 9) or vi[0] == 3 and vi < (3, 4):
        extras_require['tls'].append("wincertstore>=0.2")
else:
    extras_require['gssapi'] = ["pykerberos"]
    if vi[0] == 2 and vi < (2, 7, 9):
        extras_require['tls'].append("certifi")

extra_opts = {
    "packages": ["bson", "pymongo", "gridfs"]
}
if sys.version_info[:2] == (2, 6):
    extra_opts['tests_require'] = "unittest2"

if "--no_ext" in sys.argv:
    sys.argv.remove("--no_ext")
elif (sys.platform.startswith("java") or
      sys.platform == "cli" or
      "PyPy" in sys.version):
    sys.stdout.write("""
*****************************************************\n
The optional C extensions are currently not supported\n
by this python implementation.\n
*****************************************************\n
""")
else:
    extra_opts['ext_modules'] = ext_modules

setup(
    name="pymongo",
    version=version,
    description="Python driver for MongoDB <http://www.mongodb.org>",
    long_description=readme_content,
    author="Mike Dirolf",
    author_email="mongodb-user@googlegroups.com",
    maintainer="Bernie Hackett",
    maintainer_email="bernie@mongodb.com",
    url="http://github.com/mongodb/mongo-python-driver",
    keywords=["mongo", "mongodb", "pymongo", "gridfs", "bson"],
    install_requires=[],
    license="Apache License, Version 2.0",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Database"],
    cmdclass={"build_ext": custom_build_ext,
              "doc": doc,
              "test": test},
    extras_require=extras_require,
    **extra_opts
)
