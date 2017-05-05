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

'''

from __future__ import print_function, unicode_literals, division, absolute_import
import os, sys

import dxpy
from .utils import json_load_raise_on_duplicates

class WorkflowBuilderException(Exception):
    """
    This exception is raised by the methods in this module when workflow
    building fails.
    """
    pass

def _parse_executable_spec(src_dir, json_file_name, exception):
    """
    Returns the parsed contents of a json specification.

    Precondition: src_dir exists and contains the json file

    Raises exception (exit code 3) if this cannot be done.
    """
    if not os.path.isdir(src_dir):
        parser.error("{} is not a directory".format(src_dir))

    with open(os.path.join(src_dir, json_file_name)) as desc:
        try:
            return json_load_raise_on_duplicates(desc)
        except Exception as e:
            raise exception("Could not parse {} file as JSON: {}".format(
                            json_file_name, e.message))

def _get_destination_project(json_spec, args):
    """
    Returns destination project based on workspace env var, if not specified.
    The order of precedence is:
    1. --destination, -d option supplied with `dx build`,
    2. 'project' specified in the json file,
    3. project set in the dxpy.WORKSPACE_ID environment variable.
    """
    # TODO: need to parse the destination, extract the code part around destination_override for
    # app(let)s - dx_build_app.parse_destination
    if args.destination:
        return args.destination
    if 'project' in json_spec:
        return json_spec['project']
    if dxpy.WORKSPACE_ID:
        return dxpy.WORKSPACE_ID
    raise WorkflowBuilderException("destination project not set")

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
    return [key for key in keys if key not in supported_keys]

def _get_validated_stage(stage, stage_index):
    # required keys
    if 'executable' not in stage:
        raise WorkflowBuilderException(
            "executable is not specified for stage with index {}".format(stage_index))

    # print ignored keys if present in json_spec
    supported_keys = set(["id", "input", "executable", "name", "folder", "input"])
    unsupported_keys = _get_unsupported_keys(stage.keys(), supported_keys)
    if unsupported_keys:
        print("Warning: the following stage fields are not supported and will be ignored: {}"
              .format(",".join(unsupported_keys)))

    #TODO: validate stage input
    if 'input' in stage:
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

def _get_validated_json(json_spec, args):
    if not json_spec:
        return
    if not args:
        return

    supported_keys = set(["project", "name", "outputFolder", "stages"])
    unsupported_keys = _get_unsupported_keys(json_spec.keys(), supported_keys)
    if unsupported_keys:
        print("Warning: the following root level fields are not supported and will be ignored: {}"
              .format(",".join(unsupported_keys)))

    _inline_documentation_files(json_spec, args.src_dir)
    json_spec['project'] = _get_destination_project(json_spec, args)

    if 'stages' in json_spec:
        json_spec['stages'] = _get_validated_stages(json_spec['stages'])

    return json_spec

def _create_workflow(json_spec):
    """
    Creates a workflow on the platform and puts it in a closed state.
    Returns a workflow_id, or None if the workflow cannot be created.
    """
    try:
        workflow_id = dxpy.api.workflow_new(json_spec)["id"]
        dxpy.api.workflow_close(workflow_id)
    except dxpy.exceptions.DXAPIError as e:
        raise e
    return workflow_id

def build(args):
    """
    Validates workflow source directory and creates a new workflow based on it.
    Raises: WorkflowBuilderException if the workflow cannot be created.
    """
    if args is None:
        raise Exception("arguments not provided")

    json_spec = _parse_executable_spec(args.src_dir, "dxworkflow.json", dxpy.workflow_builder.WorkflowBuilderException)
    validated_spec = _get_validated_json(json_spec, args)
    #print("workflow_json: " + str(validated_spec))
    workflow_id = _create_workflow(validated_spec)
    return workflow_id
