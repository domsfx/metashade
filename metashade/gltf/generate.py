# Copyright 2020 Pavlo Penenko
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse, os, pathlib
from pygltflib import GLTF2

from metashade.hlsl.sm5 import vs_5_0, ps_5_0

def _generate_vs_out(sh, primitive):
    with sh.vs_output('VsOut') as VsOut:
        VsOut.SV_Position('Pclip', sh.Vector4f)
        
        VsOut.texCoord('Nw', sh.Vector3f)
        if primitive.attributes.TANGENT is not None:
            VsOut.texCoord('Tw', sh.Vector3f)
            VsOut.texCoord('Bw', sh.Vector3f)

        VsOut.texCoord('UV0', sh.Point2f)

def _generate_per_frame_uniform_buffer(sh):
    sh.struct('Light')(
        VpXf = sh.Matrix4x4f,
        direction = sh.Vector3f,
        range = sh.Float,
        color = sh.RgbF,
        intensity = sh.Float,
        position = sh.Point3f,
        innerConeCos = sh.Float,
        outerConeCos = sh.Float,
        type_ = sh.Float, # should be an int, but we assume a spotlight anyway
        depthBias = sh.Float,
        shadowMapIndex = sh.Float # should be an int, unused for now
    )

    with sh.uniform_buffer(register = 0, name = 'cbPerFrame'):
        sh.uniform('gVpXf', sh.Matrix4x4f)
        sh.uniform('gVpIXf', sh.Matrix4x4f)
        sh.uniform('gCameraPos', sh.Vector4f)
        sh.uniform('gIblFactor', sh.Float)
        sh.uniform('gEmissiveFactor', sh.Float)
        sh.uniform('PADDING', sh.Float)
        sh.uniform('gNumLights', sh.Float)   # should be int
        sh.uniform('gLight', sh.Light)      # should be an array

def _generate_vs(vs_file, primitive):
    sh = vs_5_0.Generator(vs_file)

    _generate_per_frame_uniform_buffer(sh)

    with sh.uniform_buffer(register = 1, name = 'cbPerObject'):
        sh.uniform('gWorldXf', sh.Matrix4x4f) # should be 3x3

    attributes = primitive.attributes

    with sh.vs_input('VsIn') as VsIn:
        if attributes.POSITION is None:
            raise RuntimeError('POSITION attribute is mandatory')
        VsIn.position('Pobj', sh.Point3f)

        if attributes.NORMAL is not None:
            VsIn.normal('Nobj', sh.Vector3f)

        if attributes.TANGENT is not None:
            VsIn.tangent('Tobj', sh.Vector4f)

        if attributes.TEXCOORD_0 is not None:
            VsIn.texCoord('UV0', sh.Point2f)

        if attributes.TEXCOORD_1 is not None:
            VsIn.texCoord('UV1', sh.Point2f)

        if attributes.COLOR_0 is not None:
            VsIn.color('Color0', sh.RgbaF)

        if attributes.JOINTS_0 is not None:
            raise RuntimeError('Unsupported attribute JOINTS_0')

        if attributes.WEIGHTS_0 is not None:
            raise RuntimeError('Unsupported attribute WEIGHTS_0')

    _generate_vs_out(sh, primitive)

    with sh.main('mainVS', sh.VsOut)(vsIn = sh.VsIn):
        sh.Pw = sh.gWorldXf.xform(sh.vsIn.Pobj)

        sh.vsOut = sh.VsOut()
        sh.vsOut.Pclip._ = sh.gVpXf.xform(sh.Pw)
        sh.vsOut.Nw._ = sh.gWorldXf.xform(sh.vsIn.Nobj).normalize()
        
        if attributes.TANGENT is not None:
            sh.vsOut.Tw._ = \
                sh.gWorldXf.xform(sh.vsIn.Tobj.xyz.as_vector4()).normalize()
            sh.vsOut.Bw._ = sh.vsOut.Nw.cross(sh.vsOut.Tw) * sh.vsIn.Tobj.w

        sh.vsOut.UV0._ = sh.vsIn.UV0

        sh.return_(sh.vsOut)

def _generate_ps(ps_file, material, primitive):
    sh = ps_5_0.Generator(ps_file)

    _generate_per_frame_uniform_buffer(sh)

    _generate_vs_out(sh, primitive)

    with sh.ps_output('PsOut') as PsOut:
        PsOut.SV_Target('color', sh.Float4)

    texture_set = set()

    def _add_texture(parent, name):
        if getattr(parent, name) is not None:
            texture_set.add(name)

    _add_texture(material, 'normalTexture')
    _add_texture(material, 'occlusionTexture')
    _add_texture(material, 'emissiveTexture')

    if material.pbrMetallicRoughness is not None:
        _add_texture(material.pbrMetallicRoughness, 'baseColorTexture')
        _add_texture(material.pbrMetallicRoughness, 'metallicRoughnessTexture')

    # First 3 sampler slots are reserved for the BRDF LUT and IBL textures
    # in the GLTF demo app (assuming the skydome is on)
    texture_idx = 3

    # We're sorting material textures by name
    for texture_name in sorted(texture_set):
        sh.combined_sampler_2d(
            texture_name = texture_name,
            texture_register = texture_idx,
            sampler_name = texture_name + 'Sampler',
            sampler_register = texture_idx
        )
        texture_idx += 1

    with sh.main('mainPS', sh.PsOut)(psIn = sh.VsOut):
        if primitive.attributes.TANGENT is not None:
            # See getPixelNormal()
            pass

        if material.normalTexture is not None:
            normal_uv_idx = material.normalTexture.texCoord
            if normal_uv_idx is None:
                normal_uv_idx = 0

            normal_uv = getattr(sh.psIn, "UV{}".format(normal_uv_idx))
            sh.textureNormal = sh.normalTextureSampler(normal_uv)

        sh.psOut = sh.PsOut()
        sh.lambert = sh.gLight.direction.dot(sh.psIn.Nw.normalize()).saturate()
        sh.baseColor = sh.baseColorTextureSampler(sh.psIn.UV0)
        sh.psOut.color._ = sh.lambert * sh.baseColor
        sh.return_(sh.psOut)

def main(gltf_dir, out_dir):
    os.makedirs(out_dir, exist_ok = True)

    for gltf_file in pathlib.Path(args.gltf_dir).glob('**/*.gltf'):
        print(gltf_file)
        gltf = GLTF2().load(gltf_file)

        for mesh in gltf.meshes:
            for primitive_idx, primitive in enumerate(mesh.primitives):
                def _file_name(stage : str):
                    return os.path.join(
                        out_dir,
                        '{mesh}-{i}-{stage}.hlsl'.format(
                            mesh = mesh.name,
                            i = primitive_idx,
                            stage = stage
                        )
                    )
                with open(_file_name("VS"), 'w') as vs_file:
                    _generate_vs(vs_file, primitive)

                with open(_file_name("PS"), 'w') as ps_file:
                    _generate_ps(
                        ps_file,
                        gltf.materials[primitive.material],
                        primitive
                    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description = "Generate shaders from glTF materials."
    )
    parser.add_argument("--gltf-dir", help = "Path to the source glTF assets")
    parser.add_argument("--out-dir", help = "Path to the output directory")
    args = parser.parse_args()
    
    if not os.path.isdir(args.gltf_dir):
        raise NotADirectoryError(args.gltf_dir)

    main(args.gltf_dir, args.out_dir)
