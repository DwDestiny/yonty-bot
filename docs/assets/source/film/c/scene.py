# Input: assets/ink.png、stamp.png、HDRI（CC0）  Output: 逐帧 PNG
# Pos: 方向 C「小票」Blender 场景，米制。
# 用法: blender -b -P scene.py -- ENGINES FRAMES OUTDIR SAMPLES ASSETDIR [RES%] [DEVICE]
#   ENGINES: EEVEE,CYCLES 之一或两者   FRAMES: 0,135,219 或 0-239   DEVICE: CPU|METAL（Cycles 用）
import bpy, sys, math, time, os
from mathutils import Vector
a = sys.argv[sys.argv.index('--')+1:]
engines = a[0].split(','); fr = a[1]; out = a[2]; samples = int(a[3]); assets = a[4]
pct = int(a[5]) if len(a) > 5 else 100; dev = a[6] if len(a) > 6 else 'CPU'
frames = list(range(int(fr.split('-')[0]), int(fr.split('-')[1])+1)) if '-' in fr else [int(x) for x in fr.split(',')]

W_M, H_M, TM, P = 0.058, 0.215, 0.075, 0.0125
Z0 = 0.0115 + TM + P                       # 第 1 行初始居中于 z=0.0115，出纸口在 z=0
EVENTS = {2: 0.9, 3: 1.9, 4: 3.0, 5: 5.2, 6: 6.4, 7: 7.55}   # 第 r 行被推出来的时刻（秒）
TC = 4.3                                   # 盖章接触时刻（秒），4.5 秒帧为章刚抬起、墨在晕开
MARK_ROW, MARK_DX, MARK_ROT = 4.45, 0.005, 6.0

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; r = sc.render
r.resolution_x = 1280; r.resolution_y = 720; r.resolution_percentage = pct; r.fps = 30
r.image_settings.file_format = 'PNG'
VIEW = os.environ.get('VIEW', 'Standard')     # AgX 会把红往橙推（实测色相 14°），默认用 Standard
try: sc.view_settings.view_transform = VIEW
except Exception: pass
if VIEW == 'AgX':
    try: sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception: pass

# ---- 世界：CC0 HDRI 只给反射，相机看到的是黑 ----
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
env = nt.nodes.new('ShaderNodeTexEnvironment'); env.image = bpy.data.images.load(os.path.join(assets, 'studio_small_09_1k.hdr'))
bgE = nt.nodes.new('ShaderNodeBackground'); bgE.inputs['Strength'].default_value = 0.10
bgK = nt.nodes.new('ShaderNodeBackground'); bgK.inputs['Color'].default_value = (0.002, 0.002, 0.003, 1)
lp = nt.nodes.new('ShaderNodeLightPath'); mix = nt.nodes.new('ShaderNodeMixShader'); outn = nt.nodes.new('ShaderNodeOutputWorld')
nt.links.new(env.outputs['Color'], bgE.inputs['Color'])
nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac']); nt.links.new(bgE.outputs['Background'], mix.inputs[1])
nt.links.new(bgK.outputs['Background'], mix.inputs[2]); nt.links.new(mix.outputs['Shader'], outn.inputs['Surface'])

def setin(node, names, val):
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = val; return
def newmat(name, color, rough, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes['Principled BSDF']
    setin(b, 'Base Color', color); setin(b, 'Roughness', rough); setin(b, 'Metallic', metal); return m

# ---- 纸：网格有横向弧度、纵向缓波、边缘起伏；Solidify 给厚度 ----
NX, NY = 28, 520
verts, faces = [], []
for j in range(NY+1):
    zl = -H_M*j/NY
    for i in range(NX+1):
        x = -W_M/2 + W_M*i/NX; xn = x/(W_M/2)
        y = 0.0150*xn*xn                                   # 横向卷曲（边缘离镜头更远）
        y += 0.0016*math.sin(zl*38)                         # 纵向缓波
        y += 0.0007*math.sin(zl*230 + 1.3)*abs(xn)**3       # 边缘波纹
        y += -0.0012*math.sin(zl*70+0.5)*xn                 # 轻微扭曲
        verts.append((x, y, zl))
for j in range(NY):
    for i in range(NX):
        k = j*(NX+1)+i; faces.append((k, k+1, k+NX+2, k+NX+1))
me = bpy.data.meshes.new('paper'); me.from_pydata(verts, [], faces); me.update()
uv = me.uv_layers.new(name='UV')
for poly in me.polygons:
    for li in poly.loop_indices:
        p = me.vertices[me.loops[li].vertex_index].co
        uv.data[li].uv = ((p.x+W_M/2)/W_M, 1.0 + p.z/H_M)
paper = bpy.data.objects.new('paper', me); sc.collection.objects.link(paper)
for p_ in me.polygons: p_.use_smooth = True
sd = paper.modifiers.new('thick', 'SOLIDIFY'); sd.thickness = 0.0009; sd.offset = 0

pm = bpy.data.materials.new('paper'); pm.use_nodes = True; nt = pm.node_tree; N = nt.nodes; L = nt.links; N.clear()
def node(t, **kw):
    n = N.new(t)
    for k, v in kw.items(): setattr(n, k, v)
    return n
tc_ = node('ShaderNodeTexCoord'); geo = node('ShaderNodeNewGeometry')
inkT = node('ShaderNodeTexImage'); inkT.image = bpy.data.images.load(os.path.join(assets, 'ink.png')); inkT.image.colorspace_settings.name = 'Non-Color'
L.new(tc_.outputs['UV'], inkT.inputs['Vector'])
stT = node('ShaderNodeTexImage', extension='CLIP'); stT.image = bpy.data.images.load(os.path.join(assets, 'stamp.png')); stT.image.colorspace_settings.name = 'Non-Color'
cx = 0.5*W_M + MARK_DX; cy = H_M - (TM + MARK_ROW*P)
m1 = node('ShaderNodeMapping'); m1.inputs['Scale'].default_value = (W_M, H_M, 1); m1.inputs['Location'].default_value = (-cx, -cy, 0)
m2 = node('ShaderNodeMapping'); m2.inputs['Rotation'].default_value = (0, 0, math.radians(MARK_ROT))
m3 = node('ShaderNodeMapping'); m3.inputs['Scale'].default_value = (1/0.042, 1/0.020, 1); m3.inputs['Location'].default_value = (0.5, 0.5, 0)
L.new(tc_.outputs['UV'], m1.inputs['Vector']); L.new(m1.outputs['Vector'], m2.inputs['Vector']); L.new(m2.outputs['Vector'], m3.inputs['Vector']); L.new(m3.outputs['Vector'], stT.inputs['Vector'])
sep = node('ShaderNodeSeparateXYZ'); L.new(geo.outputs['Position'], sep.inputs['Vector'])
gate = node('ShaderNodeMapRange'); gate.inputs['From Min'].default_value = 0.002; gate.inputs['From Max'].default_value = 0.007; gate.clamp = True
L.new(sep.outputs['Z'], gate.inputs['Value'])
def mathn(op, a_, b_=None, clamp=False):
    n = node('ShaderNodeMath', operation=op); n.use_clamp = clamp
    for idx, v in enumerate((a_, b_)):
        if v is None: continue
        if isinstance(v, (int, float)): n.inputs[idx].default_value = v
        else: L.new(v, n.inputs[idx])
    return n.outputs[0]
sepI = node('ShaderNodeSeparateColor'); L.new(inkT.outputs['Color'], sepI.inputs['Color'])
sepS = node('ShaderNodeSeparateColor'); L.new(stT.outputs['Color'], sepS.inputs['Color'])
# 噪声：墨的浓淡、纤维
objc = tc_.outputs['Object']
fm = node('ShaderNodeMapping'); fm.inputs['Scale'].default_value = (1800, 90, 1800); L.new(objc, fm.inputs['Vector'])
fib = node('ShaderNodeTexNoise'); fib.inputs['Scale'].default_value = 1.0; fib.inputs['Detail'].default_value = 8; fib.inputs['Roughness'].default_value = 0.7; L.new(fm.outputs['Vector'], fib.inputs['Vector'])
fm2 = node('ShaderNodeMapping'); fm2.inputs['Scale'].default_value = (500, 500, 500); L.new(objc, fm2.inputs['Vector'])
pit = node('ShaderNodeTexNoise'); pit.inputs['Detail'].default_value = 6; L.new(fm2.outputs['Vector'], pit.inputs['Vector'])
fm3 = node('ShaderNodeMapping'); fm3.inputs['Scale'].default_value = (90, 90, 90); L.new(objc, fm3.inputs['Vector'])
mott = node('ShaderNodeTexNoise'); mott.inputs['Detail'].default_value = 4; L.new(fm3.outputs['Vector'], mott.inputs['Vector'])   # 大块色斑
dens = mathn('ADD', mathn('MULTIPLY', pit.outputs['Fac'], 0.30), 0.78)           # 墨浓淡 0.78–1.08
black = mathn('MULTIPLY', mathn('MULTIPLY', sepI.outputs['Red'], gate.outputs['Result']), dens, clamp=True)
redv = node('ShaderNodeValue'); redv.name = 'presence'; bl = node('ShaderNodeValue'); bl.name = 'bleed'
mk = mathn('MAXIMUM', sepS.outputs['Red'], mathn('MULTIPLY', mathn('MULTIPLY', sepS.outputs['Green'], 1.6, clamp=True), bl.outputs[0]))
mk = mathn('MULTIPLY', mathn('MULTIPLY', mk, redv.outputs[0]), dens, clamp=True)
redk = mathn('MAXIMUM', mathn('MULTIPLY', sepI.outputs['Green'], gate.outputs['Result']), mk)
paperc = node('ShaderNodeMix', data_type='RGBA'); paperc.inputs[6].default_value = (0.92, 0.84, 0.70, 1); paperc.inputs[7].default_value = (0.84, 0.74, 0.58, 1)
L.new(mott.outputs['Fac'], paperc.inputs[0])
c1 = node('ShaderNodeMix', data_type='RGBA'); L.new(black, c1.inputs[0]); L.new(paperc.outputs[2], c1.inputs[6]); c1.inputs[7].default_value = (0.008, 0.007, 0.006, 1)
c2 = node('ShaderNodeMix', data_type='RGBA'); L.new(mathn('MULTIPLY', redk, 0.95, clamp=True), c2.inputs[0]); L.new(c1.outputs[2], c2.inputs[6]); c2.inputs[7].default_value = (0.42, 0.0, 0.012, 1)
bump = node('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.35; bump.inputs['Distance'].default_value = 0.0004
hs = mathn('ADD', mathn('MULTIPLY', fib.outputs['Fac'], 0.8), mathn('MULTIPLY', mathn('ADD', black, redk), -0.25)); L.new(hs, bump.inputs['Height'])
lw = node('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.45
shade = mathn('SUBTRACT', 1.0, mathn('MULTIPLY', lw.outputs['Facing'], 1.1))
fin = node('ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); fin.inputs[0].default_value = 1.0; L.new(c2.outputs[2], fin.inputs[6])
L.new(shade, fin.inputs[7]) if False else None
sg = node('ShaderNodeCombineColor'); L.new(shade, sg.inputs[0]); L.new(shade, sg.inputs[1]); L.new(shade, sg.inputs[2]); L.new(sg.outputs[0], fin.inputs[7])
bsdf = node('ShaderNodeBsdfPrincipled'); L.new(fin.outputs[2], bsdf.inputs['Base Color']); setin(bsdf, 'Roughness', 0.62); setin(bsdf, ['Specular IOR Level', 'Specular'], 0.35)
setin(bsdf, 'Sheen Weight', 0.3); L.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
tr = node('ShaderNodeBsdfTranslucent'); L.new(fin.outputs[2], tr.inputs['Color']); L.new(bump.outputs['Normal'], tr.inputs['Normal'])
mx = node('ShaderNodeMixShader'); mx.inputs['Fac'].default_value = 0.55; L.new(bsdf.outputs['BSDF'], mx.inputs[1]); L.new(tr.outputs['BSDF'], mx.inputs[2])
o = node('ShaderNodeOutputMaterial'); L.new(mx.outputs['Shader'], o.inputs['Surface'])
paper.data.materials.append(pm)
nvalue = {n.name: n for n in N}
PRES, BLEED = nvalue['presence'], nvalue['bleed']

# ---- 出纸口面板（深色塑料，遮住纸的下半截） ----
bpy.ops.mesh.primitive_cube_add(size=1); lip = bpy.context.object; lip.scale = (0.11, 0.006, 0.05); lip.location = (0, -0.0075, -0.025)
bpy.ops.object.transform_apply(scale=True)
bv = lip.modifiers.new('b', 'BEVEL'); bv.width = 0.0012; bv.segments = 4; bpy.ops.object.shade_smooth()
lip.data.materials.append(newmat('lip', (0.012, 0.012, 0.014, 1), 0.38))

# ---- 章：黑木块 + 红胶面 + 圆钮，原点在胶面中心，朝 +Y 是纸 ----
stamp = bpy.data.objects.new('stamp', None); sc.collection.objects.link(stamp)
def part(kind, loc, scale, mat, rot=(0, 0, 0), bevel=0.0007):
    if kind == 'cube': bpy.ops.mesh.primitive_cube_add(size=1)
    else: bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.5, depth=1)
    ob = bpy.context.object; ob.scale = scale; ob.location = loc; ob.rotation_euler = rot; bpy.ops.object.transform_apply(scale=True, rotation=True)
    b = ob.modifiers.new('b', 'BEVEL'); b.width = bevel; b.segments = 4; bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat); ob.parent = stamp; return ob
rubber = newmat('rubber', (0.40, 0.03, 0.015, 1), 0.85); wood = newmat('wood', (0.03, 0.026, 0.024, 1), 0.34)
part('cube', (0, -0.0015, 0), (0.044, 0.003, 0.021), rubber, bevel=0.0004)
part('cube', (0, -0.0140, 0), (0.040, 0.020, 0.018), wood, bevel=0.0012)
part('cyl', (0, -0.0340, 0), (0.017, 0.020, 0.017), wood, rot=(math.pi/2, 0, 0), bevel=0.0020)
stamp.rotation_mode = 'XYZ'

# ---- 背景光斑（失焦后成金色圆盘）----
import random; rnd = random.Random(11)
bm = newmat('bokeh', (1, 0.6, 0.25, 1), 1.0); nb = bm.node_tree
em = nb.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (1.0, 0.56, 0.2, 1); em.inputs['Strength'].default_value = float(os.environ.get('BOKEH', 45))
nb.links.new(em.outputs[0], nb.nodes['Material Output'].inputs['Surface'])
for _ in range(22):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=rnd.uniform(0.0015, 0.0045), segments=16, ring_count=8)
    ob = bpy.context.object; ob.location = (rnd.uniform(-0.2, 0.2), rnd.uniform(0.22, 0.6), rnd.uniform(-0.04, 0.16)); ob.data.materials.append(bm)
    if abs(ob.location.x) < 0.03 and ob.location.z < 0.08: ob.location.x += 0.09

# ---- 灯：背光（暖，隔着纸透过来）+ 一盏很弱的侧前光托出纤维 + 黑旗压暗部 ----
def mk_light(kind, name):
    l = bpy.data.lights.new(name, kind); ob = bpy.data.objects.new(name, l); sc.collection.objects.link(ob); return ob
def aim(ob, tgt): ob.rotation_euler = (Vector(tgt) - ob.location).to_track_quat('-Z', 'Y').to_euler()
back = mk_light('AREA', 'back'); back.data.shape = 'RECTANGLE'; back.data.size = 0.03; back.data.size_y = 0.06
back.location = (0.03, 0.03, 0.035); aim(back, (0, -1, 0.02)); back.data.color = (1.0, 0.60, 0.30)
back.rotation_euler = (math.radians(-90), 0, 0)
key = mk_light('SPOT', 'key'); key.data.spot_size = math.radians(30); key.data.spot_blend = 0.8; key.data.shadow_soft_size = 0.02
key.location = (-0.16, -0.12, 0.09); aim(key, (0.0, 0, 0.018)); key.data.color = (1.0, 0.86, 0.7)
back.data.energy = float(os.environ.get('BACK', 0.06)); key.data.energy = float(os.environ.get('KEY', 2.5))

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cd = cam.data; cd.sensor_fit = 'HORIZONTAL'; cd.sensor_width = 36; cd.lens = 85
cd.dof.use_dof = True; cd.dof.aperture_fstop = 2.8

def eo3(x): x = min(1, max(0, x)); return 1-(1-x)**3
def ei3(x): x = min(1, max(0, x)); return x**3
def eio(x): x = min(1, max(0, x)); return x*x*(3-2*x)
def off(t):
    s = 0.0
    for rrow, te in EVENTS.items(): s += P*eo3((t-te)/0.2)
    return s
def setframe(i):
    t = i/30.0
    # 推近 1.00→1.04（1.6–3.2 s），1.04→1.10（6.4–7.6 s）
    zoom = 1.0 + 0.04*eio((t-1.6)/1.6) + 0.06*eio((t-6.4)/1.2)
    d = 0.222/zoom
    # 章压下 / 回弹
    tau = t-TC; push = 0.0
    if 0 <= tau < 0.10: push = 0.0012*min(1, tau/0.03)
    elif tau >= 0.10:
        q = tau-0.10; push = 0.0012*math.exp(-10*q)*math.cos(28*q)
    paper.location = (0, push, Z0 + off(t))
    # 章
    tgt = Vector((MARK_DX + 0.0, 0, 0))
    mz = paper.location.z - (TM + MARK_ROW*P)
    s = 0.05; lat = Vector((0.0, 0.0)); tilt = 0.0; vis = False
    if TC-0.35 <= t < TC:
        a_ = (t-(TC-0.35))/0.35; s = 0.05*(1-a_**3)+0.0005; lat = Vector((0.08, 0.04))*(1-a_)**2; vis = True
    elif TC <= t < TC+0.10: s = 0.0004; vis = True
    elif TC+0.10 <= t < TC+0.55:
        b = (t-(TC+0.10))/0.45; s = 0.05*(1-(1-b)**2)+0.0004; lat = Vector((0.07, 0.035))*b*b; tilt = 0.30*b; vis = True
    for ob_ in [stamp]+list(stamp.children): ob_.hide_render = not vis
    stamp.location = (MARK_DX+lat.x, -s+push, mz+lat.y); stamp.rotation_euler = (tilt, 0, math.radians(MARK_ROT))
    PRES.outputs[0].default_value = 1.0 if t >= TC else 0.0
    BLEED.outputs[0].default_value = eo3((t-TC)/0.18)
    # 相机：慢漂 + 章落后微震
    sh = 0.0004*math.exp(-14*tau)*math.sin(95*tau) if 0 <= tau < 0.5 else 0.0
    cam.location = (0.004 - 0.008*t/8.0 + sh, -d, 0.0185 - 0.0015*t/8.0 + 0.6*sh); aim(cam, (cam.location.x*0.7, 0, cam.location.z)); cd.dof.focus_distance = d

def set_engine(name):
    if name == 'CYCLES':
        r.engine = 'CYCLES'; c = sc.cycles; c.samples = samples; c.use_denoising = os.environ.get('NODENOISE') != '1'; c.max_bounces = 10; c.transmission_bounces = 8; c.transparent_max_bounces = 8
        c.sample_clamp_indirect = 10
        try: c.denoiser = 'OPENIMAGEDENOISE'
        except Exception: pass
        try: c.use_motion_blur = True; r.motion_blur_shutter = 0.5
        except Exception: pass
        try: r.use_motion_blur = True
        except Exception: pass
        if dev == 'METAL':
            p = bpy.context.preferences.addons['cycles'].preferences; p.compute_device_type = 'METAL'; p.get_devices()
            for dv in p.devices: dv.use = True
            c.device = 'GPU'
        else: c.device = 'CPU'
    else:
        eng = bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys()
        r.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in eng else 'BLENDER_EEVEE'
        e = sc.eevee
        for k, v in (('taa_render_samples', samples), ('use_raytracing', True), ('use_shadows', True), ('use_ssr', True), ('use_gtao', True), ('use_bloom', True),
                     ('use_soft_shadows', True), ('use_motion_blur', True), ('motion_blur_shutter', 0.5), ('bloom_threshold', 1.0), ('bloom_intensity', 0.15)):
            try: setattr(e, k, v)
            except Exception: pass
        try: r.use_motion_blur = True; r.motion_blur_shutter = 0.5
        except Exception: pass

res = []
for en in engines:
    en = en.strip().upper(); set_engine(en); od = os.path.join(out, 'cy' if en == 'CYCLES' else 'ev'); os.makedirs(od, exist_ok=True)
    secs = []
    for i in frames:
        setframe(i); r.filepath = os.path.join(od, f'c{i:04d}.png'); t0 = time.time(); bpy.ops.render.render(write_still=True); secs.append(round(time.time()-t0, 1))
    res.append((en, secs))
print('RESULT', res, 'blender', bpy.app.version_string, 'samples', samples, 'res%', pct)
