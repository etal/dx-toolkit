#!/usr/bin/env python
#
# Copyright (C) 2013-2016 DNAnexus, Inc.
#
# This file is part of dx-toolkit (DNAnexus platform client libraries).
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may not
#   use this file except in compliance with the License. You may obtain a copy
#   of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.


'''
Executable Builder
+++++++++++++++++++

Contains utility methods useful for deploying executables (apps, applets, workflows)
onto the platform.

It has two responsibilities: parsing arguments supplied to `dx build` and determining
what builder (app_builder or workflow_builder) to invoke.

'''

from __future__ import print_function, unicode_literals, division, absolute_import

import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger('requests.packages.urllib3.connectionpool').setLevel(logging.ERROR)

import os, sys, argparse
import re
import dxpy
from dxpy import app_builder
from dxpy import workflow_builder
from .scripts import dx_build_app

from .utils.completer import LocalCompleter
from .utils.printing import BOLD
from .compat import open, USING_PYTHON2, decode_command_line_args, basestring


class ExecutableBuilderException(Exception):
    """
    This exception is raised by the methods in this module
    when executable building fails.
    """
    pass

decode_command_line_args()

parser = argparse.ArgumentParser(description="Uploads a DNAnexus App, Applet or Workflow.")

APP_VERSION_RE = re.compile("^([1-9][0-9]*|0)\.([1-9][0-9]*|0)\.([1-9][0-9]*|0)(-[-0-9A-Za-z]+(\.[-0-9A-Za-z]+)*)?(\+[-0-9A-Za-z]+(\.[-0-9A-Za-z]+)*)?$")

app_options = parser.add_argument_group('options for creating apps', '(Only valid when --app/--create-app is specified)')
applet_and_workflow_options = parser.add_argument_group('options for creating applets or workflows', '(Only valid when --app/--create-app is NOT specified)')

# COMMON OPTIONS
parser.add_argument("--ensure-upload", help="If specified, will bypass computing checksum of " +
                                            "resources directory and upload it unconditionally; " +
                                            "by default, will compute checksum and upload only if " +
                                            "it differs from a previously uploaded resources bundle.",
                    action="store_true")
parser.add_argument("--force-symlinks", help="If specified, will not attempt to dereference "+
                                            "symbolic links pointing outside of the resource " +
                                            "directory.  By default, any symlinks within the resource " +
                                            "directory are kept as links while links to files " +
                                            "outside the resource directory are dereferenced (note "+
                                            "that links to directories outside of the resource directory " +
                                            "will cause an error).",
                    action="store_true")

src_dir_action = parser.add_argument("src_dir", help="App, applet, or workflow source directory (default: current directory)", nargs='?')
src_dir_action.completer = LocalCompleter()

parser.add_argument("--app", "--create-app", help="Create an app (otherwise, creates an applet or a workflow)", action="store_const",
                    dest="mode", const="app")
parser.add_argument("--create-applet", help=argparse.SUPPRESS, action="store_const", dest="mode", const="applet")

applet_and_workflow_options.add_argument("-d", "--destination", help="Specifies the destination project, destination folder, and/or name for the applet, in the form [PROJECT_NAME_OR_ID:][/[FOLDER/][NAME]]. Overrides the project, folder, and name fields of the dxapp.json, if they were supplied.", default='.')

# --[no-]dry-run
#
# The --dry-run flag can be used to see the applet spec that would be
# provided to /applet/new, for debugging purposes. However, the output
# would deviate from that of a real run in the following ways:
#
# * Any bundled resources are NOT uploaded and are not reflected in the
#   app(let) spec.
# * No temporary project is created (if building an app) and the
#   "project" field is not set in the app spec.
parser.set_defaults(dry_run=False)
parser.add_argument("--dry-run", "-n", help="Do not create an app(let): only perform local checks and compilation steps, and show the spec of the app(let) that would have been created.", action="store_true", dest="dry_run")
parser.add_argument("--no-dry-run", help=argparse.SUPPRESS, action="store_false", dest="dry_run")

# --[no-]publish
app_options.set_defaults(publish=False)
app_options.add_argument("--publish", help="Publish the resulting app and make it the default.", action="store_true",
                         dest="publish")
app_options.add_argument("--no-publish", help=argparse.SUPPRESS, action="store_false", dest="publish")


# --[no-]remote
parser.set_defaults(remote=False)
parser.add_argument("--remote", help="Build the app remotely by uploading the source directory to the DNAnexus Platform and building it there. This option is useful if you would otherwise need to cross-compile the app(let) to target the Execution Environment.", action="store_true", dest="remote")
parser.add_argument("--no-watch", help="Don't watch the real-time logs of the remote builder. (This option only applicable if --remote was specified).", action="store_false", dest="watch")
parser.add_argument("--no-remote", help=argparse.SUPPRESS, action="store_false", dest="remote")

applet_and_workflow_options.add_argument("-f", "--overwrite", help="Remove existing applet(s) of the same name in the destination folder.",
                            action="store_true", default=False)
applet_and_workflow_options.add_argument("-a", "--archive", help="Archive existing applet(s) of the same name in the destination folder.",
                            action="store_true", default=False)
parser.add_argument("-v", "--version", help="Override the version number supplied in the manifest.", default=None,
                    dest="version_override", metavar='VERSION')
app_options.add_argument("-b", "--bill-to", help="Entity (of the form user-NAME or org-ORGNAME) to bill for the app.",
                         default=None, dest="bill_to", metavar='USER_OR_ORG')

# --[no-]check-syntax
parser.set_defaults(check_syntax=True)
parser.add_argument("--check-syntax", help=argparse.SUPPRESS, action="store_true", dest="check_syntax")
parser.add_argument("--no-check-syntax", help="Warn but do not fail when syntax problems are found (default is to fail on such errors)", action="store_false", dest="check_syntax")

# --[no-]version-autonumbering
app_options.set_defaults(version_autonumbering=True)
app_options.add_argument("--version-autonumbering", help=argparse.SUPPRESS, action="store_true", dest="version_autonumbering")
app_options.add_argument("--no-version-autonumbering", help="Only attempt to create the version number supplied in the manifest (that is, do not try to create an autonumbered version such as 1.2.3+git.ab1b1c1d if 1.2.3 already exists and is published).", action="store_false", dest="version_autonumbering")
# --[no-]update
app_options.set_defaults(update=True)
app_options.add_argument("--update", help=argparse.SUPPRESS, action="store_true", dest="update")
app_options.add_argument("--no-update", help="Never update an existing unpublished app in place.", action="store_false", dest="update")
# --[no-]dx-toolkit-autodep
parser.set_defaults(dx_toolkit_autodep="stable")
parser.add_argument("--dx-toolkit-legacy-git-autodep", help=argparse.SUPPRESS, action="store_const", dest="dx_toolkit_autodep", const="git")
parser.add_argument("--dx-toolkit-stable-autodep", help=argparse.SUPPRESS, action="store_const", dest="dx_toolkit_autodep", const="stable")
parser.add_argument("--dx-toolkit-autodep", help=argparse.SUPPRESS, action="store_const", dest="dx_toolkit_autodep", const="stable")
parser.add_argument("--no-dx-toolkit-autodep", help="Do not auto-insert the dx-toolkit dependency (default is to add it if it would otherwise be absent from the runSpec)", action="store_false", dest="dx_toolkit_autodep")

# --[no-]parallel-build
parser.set_defaults(parallel_build=True)
parser.add_argument("--parallel-build", help=argparse.SUPPRESS, action="store_true", dest="parallel_build")
parser.add_argument("--no-parallel-build", help="Build with " + BOLD("make") + " instead of " + BOLD("make -jN") + ".", action="store_false",
                    dest="parallel_build")

app_options.set_defaults(use_temp_build_project=True)
# Original help: "When building an app, build its applet in the current project instead of a temporary project".
app_options.add_argument("--no-temp-build-project", help=argparse.SUPPRESS, action="store_false", dest="use_temp_build_project")

# --yes
app_options.add_argument('-y', '--yes', dest='confirm', help='Do not ask for confirmation for potentially dangerous operations', action='store_false')

# --[no-]json (undocumented): dumps the JSON describe of the app or
# applet that was created. Useful for tests.
parser.set_defaults(json=False)
parser.add_argument("--json", help=argparse.SUPPRESS, action="store_true", dest="json")
parser.add_argument("--no-json", help=argparse.SUPPRESS, action="store_false", dest="json")

parser.add_argument("--extra-args", help="Arguments (in JSON format) to pass to the /applet/new API method, overriding all other settings")
parser.add_argument("--run", help="Run the app or applet after building it (options following this are passed to "+BOLD("dx run")+"; run at high priority by default)", nargs=argparse.REMAINDER)

# --region
app_options.add_argument("--region", action="append", help="Enable the app in this region. This flag can be specified multiple times to enable the app in multiple regions. If --region is not specified, then the enabled region(s) will be determined by 'regionalOptions' in dxapp.json, or the project context.")

def _get_mode(src_dir):
    """
    Returns an app/applet builder or a workflow builder based on whether
    the source directory contains dxapp.json or dxworkflow.json.

    Raises ExecutableBuilderException (exit code 2) if this cannot be done.
    """
    if not os.path.isdir(src_dir):
        parser.error("{} is not a directory".format(src_dir))

    if os.path.exists(os.path.join(src_dir, "dxapp.json")):
        return "app"
    elif os.path.exists(os.path.join(src_dir, "dxworkflow.json")):
        return "workflow"
    else:
        raise ExecutableBuilderException(
            "Directory {} does not contain dxapp.json nor dxworkflow.json: not a valid DNAnexus source directory"
            .format(src_dir))

def _get_validated_source_dir(args):
    src_dir = args.src_dir
    if src_dir is None:
        src_dir = os.getcwd()
        if USING_PYTHON2:
            src_dir = src_dir.decode(sys.getfilesystemencoding())
    return src_dir

def _handle_arg_conflicts(args):
    """
    Raises parser error (exit code 3) if there are any conflicts in the specified options.
    """
    if args.mode == "app" and args.destination != '.':
        parser.error("--destination cannot be used when creating an app (only an applet)")

    if args.mode == "applet" and args.region:
        parser.error("--region cannot be used when creating an applet (only an app)")

    if args.overwrite and args.archive:
        parser.error("Options -f/--overwrite and -a/--archive cannot be specified together")

    if args.run is not None and args.dry_run:
        parser.error("Options --dry-run and --run cannot be specified together")

    if args.run and args.remote and args.mode == 'app':
        parser.error("Options --remote, --app, and --run cannot all be specified together. Try removing --run and then separately invoking dx run.")

    # options not supported by workflow building
    #TODO: for better experience report all the unsupported options at once
    print("args: " + str(args))
    if args.mode == "workflow":
         if args.ensure_upload:
             parser.error("Option --ensure-upload is not supported for workflows.")
         if args.force_symlinks:
             parser.error("Option --force-symlinks is not supported for workflows.")
         if args.publish:
             parser.error("Option --publish is not yet supported for workflows.")

#args: Namespace(archive=False, bill_to=None, check_syntax=True, confirm=True, destination=u'.', dry_run=False, dx_toolkit_autodep=u'stable', ensure_upload=False, extra_args=None, force_symlinks=False, json=False, mode=u'workflow', overwrite=False, parallel_build=True, publish=False, region=None, remote=False, run=None, src_dir=u'/home/commandlinegirl/repos/dx-toolkit/workflow-with-applet', update=True, use_temp_build_project=True, version_autonumbering=True, version_override=None, watch=True)

def build(**kwargs):

    if len(sys.argv) > 0:
        if sys.argv[0].endswith('dx-build-app'):
            warn_mesg = 'Warning: dx-build-app has been replaced with "dx build --create-app".'
            warn_mesg += 'Please update your scripts.'
            logging.warn(warn_mesg)
        elif sys.argv[0].endswith('dx-build-applet'):
            warn_mesg = 'Warning: dx-build-applet has been replaced with "dx build --create-applet".'
            warn_mesg += 'Please update your scripts.'
            logging.warn(warn_mesg)

    if len(kwargs) == 0:
        args = parser.parse_args()
    else:
        args = parser.parse_args(**kwargs)

    if dxpy.AUTH_HELPER is None and not args.dry_run:
        parser.error('Authentication required to build an executable on the platform; please run "dx login" first')

    args.src_dir = _get_validated_source_dir(args)

    # If mode is not specified, determine it by the json file
    if args.mode is None:
        args.mode = _get_mode(args.src_dir)

    _handle_arg_conflicts(args)

    if args.mode in ("app", "applet"):
        dx_build_app.build(args)
    elif args.mode == "workflow":
        workflow_builder.build(args)
    else:
        print("--mode is not set, I don't know what to build. Accepted values: app, applet, workflow")
    return
