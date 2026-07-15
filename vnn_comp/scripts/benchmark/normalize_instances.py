#!/usr/bin/env python3
"""Normalize onnx/vnnlib paths in a generated instances.csv.

The export tree and the to_vnnlib2 converter both expect each instances.csv row to
reference files at paths that resolve from the benchmark directory (typically
``onnx/<f>,vnnlib/<f>``). Some benchmarks instead emit bare filenames
(``model.onnx``) or wrong paths (``vnnlib/nns/model.onnx`` when the model is in
``onnx/``), which makes to_vnnlib2 fail with "model not found".

Rule (conservative): only rewrite a field when it does NOT resolve as-is but its
basename DOES resolve in the expected dir. Paths that already resolve — including
legitimately nested ones — are left untouched.

Usage: normalize_instances.py <instances.csv> <onnx_dir> <vnnlib_dir>
"""
import os
import sys

csv_path, onnx_dir, vnnlib_dir = sys.argv[1], sys.argv[2], sys.argv[3]


def fix(field, directory):
    name = field.strip()
    if not name or os.path.exists(name):
        return field
    candidate = os.path.join(directory, os.path.basename(name))
    if os.path.exists(candidate):
        return directory + "/" + os.path.basename(name)
    return field


with open(csv_path) as f:
    lines = f.readlines()

out = []
for line in lines:
    row = line.rstrip("\n")
    parts = row.split(",")
    if len(parts) >= 2:
        parts[0] = fix(parts[0], onnx_dir)
        parts[1] = fix(parts[1], vnnlib_dir)
        row = ",".join(parts)
    out.append(row)

with open(csv_path, "w") as f:
    f.write("\n".join(out) + "\n")
