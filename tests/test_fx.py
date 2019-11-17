# Copyright 2018 Pavlo Penenko
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

"""
An example of generating an HLSL effect with a trivial VS/PS pair.
"""

import sys

import metashade.hlsl.profile as profile
import metashade.hlsl.data_types as t
import metashade.hlsl.fx as fx

def test_simple():
    with open("test_simple.fx", "w+") as f:
        sh = profile.Generator(f)
        
        sh.uniform('diffuse_color', t.RGBA)
        sh.uniform('WvpXf', t.Matrix4x4f, semantic = 'WorldViewProjection')

        with sh.vs_input('VsIn') as vs_in:
            vs_in.position('Po', t.Point3f)

        with sh.vs_output('VsOut') as vs_out:
            vs_out.position('Pclip', t.Vector4f)

        with sh.vs_main('VsMain', sh.VsOut)(i = sh.VsIn):
            sh.o = sh.VsOut()
            sh.o.Pclip._ = t.Vector4f((0, 0, 0, 1))
            sh.return_(sh.o)
        
        sh.ps_output('PsOut')(color = t.RGBA)
        
        with sh.ps_main('PsMain', sh.PsOut)():
            sh.o = sh.PsOut()
            sh.o.color._ = sh.diffuse_color
            sh.return_(sh.o)
            
        fx.simple_vs_ps_technique(sh, 'VsMain', 'PsMain')
