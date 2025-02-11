# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# CPU kernels for struct2tensors.

"""TensorFlow Data Validation external dependencies that can be loaded in WORKSPACE files.
"""

load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository", "new_git_repository")
load("@org_tensorflow//tensorflow:workspace.bzl", "tf_workspace")

def struct2tensor_workspace():
    """All TensorFlow Data Validation external dependencies."""
    tf_workspace(
        path_prefix = "",
        tf_repo_name = "org_tensorflow",
    )

    # Fetch tf.Metadata repo from GitHub.
    git_repository(
        name = "com_github_tensorflow_metadata",
        commit = "8452a799153412972a4fbf00b9a019db23ef60f9",
        remote = "https://github.com/tensorflow/metadata.git",
    )
