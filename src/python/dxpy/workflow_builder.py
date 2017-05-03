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
Workflow Builder Library
+++++++++++++++++++

Contains utility methods useful for deploying workflows onto the platform.

You can specify the destination project in the following ways (with the earlier
ones taking precedence):

* Supply the *project* argument to :func:`upload_resources()` or
  :func:`upload_applet()`.
* Supply the 'project' attribute in your ``dxworkflow.json``.
* Set the ``DX_WORKSPACE_ID`` environment variable (when running in a job context).

You can use the function :func:`get_destination_project` to determine
the effective destination project.

'''

from __future__ import print_function, unicode_literals, division, absolute_import

import os, sys, json, subprocess, tempfile, multiprocessing
import datetime
import gzip
import hashlib
import io
import tarfile
import stat

import dxpy
from . import logger
from .utils import merge
from .utils.printing import fill
from .compat import input
from .utils import json_load_raise_on_duplicates


class WorkflowBuilderException(Exception):
    """
    This exception is raised by the methods in this module when workflow
    building fails.
    """
    pass

def _parse_executable_spec(src_dir, json_file_name, exception):
    """Returns the parsed contents of a json specification.

    Precondition: src_dir exists and contains the json file

    Raises exception (exit code 3) if this cannot be done.
    """
    if not os.path.isdir(src_dir):
        parser.error("{} is not a directory".format(src_dir))

    with open(os.path.join(src_dir, json_file_name)) as desc:
        try:
            return json_load_raise_on_duplicates(desc)
        except Exception as e:
            raise exception("Could not parse {} file as JSON: {}".format(json_file_name, e.message))

def _add_project_to_spec(json_spec):
    if 'project' not in json_spec:
        json_spec['project'] = dxpy.WORKSPACE_ID
    if not json_spec['project']:
        raise WorkflowBuilderException("project not set")

def _inline_documentation_files(json_spec, src_dir):
    """
    Modifies the provided json_spec dict to inline the contents of
    the readme file into "description" and the developer readme
    into "developerNotes".
    """
    # Inline description from a readme file
    if 'description' not in json_spec:
        readme_filename = None
        for filename in 'README.md', 'Readme.md', 'readme.md':
            if os.path.exists(os.path.join(src_dir, filename)):
                readme_filename = filename
                break
        if readme_filename is not None:
            with open(os.path.join(src_dir, readme_filename)) as fh:
                json_spec['description'] = fh.read()

    # Inline developerNotes from Readme.developer.md
    if 'developerNotes' not in json_spec:
        for filename in 'README.developer.md', 'Readme.developer.md', 'readme.developer.md':
            if os.path.exists(os.path.join(src_dir, filename)):
                with open(os.path.join(src_dir, filename)) as fh:
                    json_spec['developerNotes'] = fh.read()
                break

def _get_unsupported_keys(keys, supported_keys):
    """
    type supported_keys: set
    """
    return [key for key in keys if key not in supported_keys]

def _get_validated_stage(stage, stage_index):
    """
    """
    # required keys
    if 'executable' not in stage:
        raise WorkflowBuilderException("executable is missing from stage number {}" + stage_index)

    # ignored keys
    supported_keys = set("id", "input", "executable", "name", "folder", "input")
    unsupported_keys = _get_unsupported_keys(stage.keys(), supported_keys)
    if unsupported_keys:
        print("Warning: the following stage fields are not supported and will be ignored: {}"
              .format(",".join(unsupported_keys)))

    # validate stage input
    if 'input' in stage:
        # convert stageID.field format to $dnanexus_link that apiserver can understand
        pass

    return stage

def  _get_validated_stages(stages):
    """
    """
    if not isinstance(stages, list):
        raise WorkflowBuilderException("Stages must be specified as an array or mappings")
    validated_stages = []
    for index, stage in enumerate(stages):
        validated_stages.append(_get_validated_stage(stage, index))
    return validated_stages

def _get_validated_json(json_spec, src_dir):
    if not json_spec:
        return
    if not src_dir:
        return

    supported_keys = set(["project", "name", "outputFolder", "stages"])
    unsupported_keys = _get_unsupported_keys(json_spec.keys(), supported_keys)
    if unsupported_keys:
        print("Warning: the following root level fields are not supported and will be ignored: {}"
              .format(",".join(unsupported_keys)))

    _inline_documentation_files(json_spec, src_dir)
    _add_project_to_spec(json_spec)

    if 'stages' in json_spec:
        json_spec['stages'] = _get_validated_stages(json_spec['stages'])

    return json_spec

def _create_workflow(workflow_spec):
    """
    Creates a workflow on the platform. Returns a workflow_id,
    or None if the workflow cannot be created.
    """
    try:
        workflow_id = dxpy.api.workflow_new(workflow_spec)["id"]
    except dxpy.exceptions.DXAPIError as e:
        raise e
    return workflow_id

def build_workflow(src_dir, args):
    """
    Validates workflow source directory and creates a new workflow based on it.
    Raises: WorkflowBuilderException is unsuccessful.
    """
    json_spec = _parse_executable_spec(src_dir, "dxworkflow.json", dxpy.workflow_builder.WorkflowBuilderException)
    validated_spec = _get_validated_json(json_spec, src_dir)
    print("workflow_json: " + str(validated_spec))
    workflow_id = _create_workflow(validated_spec)
    return workflow_id
