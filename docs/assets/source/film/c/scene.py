# Input: assets/ink.png、stamp.png、HDRI（CC0）  Output: 逐帧 PNG
# Pos: 方向 C「小票」Blender 场景，米制。整套出纸口+纸+章挂在 rig 上，rig 斜放，镜头偏低偏侧。
# 用法: blender -b -P scene.py -- ENGINES FRAMES OUTDIR SAMPLES ASSETDIR [RES%] [DEVICE]
#   ENGINES: EEVEE,CYCLES 之一或两者   FRAMES: 0,135,219 或 0-239   DEVICE: CPU|METAL（Cycles 用）
# 调光环境变量: BACK KEY BOKEH EDGE SLOT VIEW NODENOISE
import bpy, sys, math, time, os, random
from mathutils import Vector, Matrix
a = sys.argv[sys.argv.index('--')+1:]
engines = a[0].split(','); fr = a[1]; out = a[2]; samples = int(a[3]); assets = a[4]
pct = int(a[5]) if len(a) > 5 else 100; dev = a[6] if len(a) > 6 else 'CPU'
frames = list(range(int(fr.split('-')[0]), int(fr.split('-')[1])+1)) if '-' in fr else [int(x) for x in fr.split(',')]
env = lambda k, d: float(os.environ.get(k, d))

W_M, H_M, TM, P = 0.046, 0.215, 0.075, 0.0125
Z0 = 0.0115 + TM + P                       # 第 1 行初始居中于 z=0.0115，出纸口在 z=0（rig 局部）
R = [0, 1, 2, 3, 4, 6.3, 7.3, 8.3]         # 各行在纸上的位置（行距 P 的倍数）；章（5.3 行）上下留空
# (开始秒, 走纸行数, 格数)：一格一格往外走，每格 0.09 s
EVENTS = [(0.15, 1, 5), (1.3, 1, 5), (2.5, 1, 5), (3.4, 1.3, 5), (5.0, 1.0, 5), (6.2, 1.0, 5), (7.35, 1.0, 5)]
TC = 4.28                                  # 盖章接触时刻；4.5 秒帧为章刚抬走、墨在渗开
MARK_ROW, MARK_DX, MARK_ROT = 5.3, 0.007, 6.0
PROG = [(1.8, 2.4, 0.0, 0.2), (5.45, 6.15, 0.2, 0.7)]   # 复跑进度格点亮：(起, 止, 从, 到)
RIG_ROT = (math.radians(-24), math.radians(14), math.radians(-8))   # 俯仰（纸往上走远）、画面内斜 14°、偏转

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; r = sc.render
r.resolution_x = 1280; r.resolution_y = 720; r.resolution_percentage = pct; r.fps = 30
r.image_settings.file_format = 'PNG'
VIEW = os.environ.get('VIEW', 'Standard')
try: sc.view_settings.view_transform = VIEW
except Exception: pass
if VIEW == 'AgX':
    try: sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception: pass

# ---- 世界：CC0 HDRI 只给反射，相机看到的是黑 ----
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
envt = nt.nodes.new('ShaderNodeTexEnvironment'); envt.image = bpy.data.images.load(os.path.join(assets, 'studio_small_09_1k.hdr'))
bgE = nt.nodes.new('ShaderNodeBackground'); bgE.inputs['Strength'].default_value = 0.08
bgK = nt.nodes.new('ShaderNodeBackground'); bgK.inputs['Color'].default_value = (0.0015, 0.0015, 0.002, 1)
lp = nt.nodes.new('ShaderNodeLightPath'); mix = nt.nodes.new('ShaderNodeMixShader'); outn = nt.nodes.new('ShaderNodeOutputWorld')
nt.links.new(envt.outputs['Color'], bgE.inputs['Color'])
nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac']); nt.links.new(bgE.outputs['Background'], mix.inputs[1])
nt.links.new(bgK.outputs['Background'], mix.inputs[2]); nt.links.new(mix.outputs['Shader'], outn.inputs['Surface'])

def setin(node, names, val):
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = val; return
def newmat(name, color, rough, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes['Principled BSDF']
    setin(b, 'Base Color', color); setin(b, 'Roughness', rough); setin(b, 'Metallic', metal); return m

rig = bpy.data.objects.new('rig', None); sc.collection.objects.link(rig)
def adopt(ob): ob.parent = rig; return ob

# ---- 纸：横向弧度、纵向缓波、边缘起伏；Solidify 给厚度 ----
NX, NY = 28, 520
verts, faces = [], []
for j in range(NY+1):
    zl = -H_M*j/NY
    for i in range(NX+1):
        x = -W_M/2 + W_M*i/NX; xn = x/(W_M/2)
        y = 0.0035*xn*xn                                    # 横向卷曲（边缘离镜头更远）
        y += 0.0016*math.sin(zl*38) + 0.0007*math.sin(zl*120+0.7)    # 纵向波
        y += 0.0008*math.sin(zl*230 + 1.3)*abs(xn)**3       # 边缘波纹
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
paper = bpy.data.objects.new('paper', me); sc.collection.objects.link(paper); adopt(paper)
for p_ in me.polygons: p_.use_smooth = True
sd = paper.modifiers.new('thick', 'SOLIDIFY'); sd.thickness = 0.0012; sd.offset = 0

pm = bpy.data.materials.new('paper'); pm.use_nodes = True; nt = pm.node_tree; N = nt.nodes; L = nt.links; N.clear()
def node(t, **kw):
    n = N.new(t)
    for k, v in kw.items(): setattr(n, k, v)
    return n
def mathn(op, a_, b_=None, clamp=False):
    n = node('ShaderNodeMath', operation=op); n.use_clamp = clamp
    for idx, v in enumerate((a_, b_)):
        if v is None: continue
        if isinstance(v, (int, float)): n.inputs[idx].default_value = v
        else: L.new(v, n.inputs[idx])
    return n.outputs[0]
def value(name):
    n = node('ShaderNodeValue'); n.name = name; return n
tc_ = node('ShaderNodeTexCoord')
inkT = node('ShaderNodeTexImage'); inkT.image = bpy.data.images.load(os.path.join(assets, 'ink.png')); inkT.image.colorspace_settings.name = 'Non-Color'
inkT.interpolation = 'Linear'; L.new(tc_.outputs['UV'], inkT.inputs['Vector'])
stT = node('ShaderNodeTexImage', extension='CLIP'); stT.image = bpy.data.images.load(os.path.join(assets, 'stamp.png')); stT.image.colorspace_settings.name = 'Non-Color'
cx = 0.5*W_M + MARK_DX; cy = H_M - (TM + MARK_ROW*P)
m1 = node('ShaderNodeMapping'); m1.inputs['Scale'].default_value = (W_M, H_M, 1); m1.inputs['Location'].default_value = (-cx, -cy, 0)
m2 = node('ShaderNodeMapping'); m2.inputs['Rotation'].default_value = (0, 0, math.radians(MARK_ROT))
m3 = node('ShaderNodeMapping'); m3.inputs['Scale'].default_value = (1/0.026, 1/0.013, 1); m3.inputs['Location'].default_value = (0.5, 0.5, 0)
L.new(tc_.outputs['UV'], m1.inputs['Vector']); L.new(m1.outputs['Vector'], m2.inputs['Vector']); L.new(m2.outputs['Vector'], m3.inputs['Vector']); L.new(m3.outputs['Vector'], stT.inputs['Vector'])
objc = tc_.outputs['Object']
sepO = node('ShaderNodeSeparateXYZ'); L.new(objc, sepO.inputs['Vector'])
zoff = value('zoff'); rigz = mathn('ADD', sepO.outputs['Z'], zoff.outputs[0])       # rig 局部高度（出纸口=0）
gate = node('ShaderNodeMapRange'); gate.inputs['From Min'].default_value = 0.002; gate.inputs['From Max'].default_value = 0.007; gate.clamp = True
L.new(rigz, gate.inputs['Value'])
sepI = node('ShaderNodeSeparateColor'); L.new(inkT.outputs['Color'], sepI.inputs['Color'])
sepS = node('ShaderNodeSeparateColor'); L.new(stT.outputs['Color'], sepS.inputs['Color'])
fm = node('ShaderNodeMapping'); fm.inputs['Scale'].default_value = (2600, 110, 2600); L.new(objc, fm.inputs['Vector'])
fib = node('ShaderNodeTexNoise'); fib.inputs['Detail'].default_value = 8; fib.inputs['Roughness'].default_value = 0.7; L.new(fm.outputs['Vector'], fib.inputs['Vector'])
fm2 = node('ShaderNodeMapping'); fm2.inputs['Scale'].default_value = (500, 500, 500); L.new(objc, fm2.inputs['Vector'])
pit = node('ShaderNodeTexNoise'); pit.inputs['Detail'].default_value = 6; L.new(fm2.outputs['Vector'], pit.inputs['Vector'])
fm3 = node('ShaderNodeMapping'); fm3.inputs['Scale'].default_value = (90, 90, 90); L.new(objc, fm3.inputs['Vector'])
mott = node('ShaderNodeTexNoise'); mott.inputs['Detail'].default_value = 4; L.new(fm3.outputs['Vector'], mott.inputs['Vector'])
fm4 = node('ShaderNodeMapping'); fm4.inputs['Scale'].default_value = (900, 900, 900); L.new(objc, fm4.inputs['Vector'])
wrk = node('ShaderNodeTexNoise'); wrk.inputs['Detail'].default_value = 3; L.new(fm4.outputs['Vector'], wrk.inputs['Vector'])        # 压痕褶皱
mr = node('ShaderNodeMapRange'); mr.inputs['From Min'].default_value = 0.30; mr.inputs['From Max'].default_value = 0.62; mr.inputs['To Min'].default_value = 0.9; mr.inputs['To Max'].default_value = 1.8; mr.clamp = True
L.new(pit.outputs['Fac'], mr.inputs['Value']); dens = mr.outputs['Result']
prog = value('prog')
lit = mathn('MULTIPLY', mathn('LESS_THAN', sepI.outputs['Blue'], mathn('ADD', prog.outputs[0], 0.005)), mathn('GREATER_THAN', sepI.outputs['Blue'], 0.01))
black = mathn('MULTIPLY', mathn('MULTIPLY', mathn('MAXIMUM', sepI.outputs['Red'], lit), gate.outputs['Result']), mathn('MULTIPLY', dens, 1.5), clamp=True)
presence = value('presence'); bleed = value('bleed'); wet = value('wet'); dent = value('dent')
bl_ = mathn('MULTIPLY', mathn('SUBTRACT', mathn('MULTIPLY', sepS.outputs['Green'], 1.2), 0.25, clamp=True), mathn('MULTIPLY', bleed.outputs[0], 0.6))
mk = mathn('MAXIMUM', sepS.outputs['Red'], bl_)
mk = mathn('MULTIPLY', mathn('MULTIPLY', mk, presence.outputs[0]), mathn('ADD', mathn('MULTIPLY', dens, 0.25), 0.78), clamp=True)
redk = mathn('MAXIMUM', mathn('MULTIPLY', sepI.outputs['Green'], gate.outputs['Result']), mk)
paperc = node('ShaderNodeMix', data_type='RGBA'); paperc.inputs[6].default_value = (0.93, 0.89, 0.81, 1); paperc.inputs[7].default_value = (0.86, 0.81, 0.72, 1)
L.new(mathn('ADD', mathn('MULTIPLY', mott.outputs['Fac'], 0.6), mathn('MULTIPLY', fib.outputs['Fac'], 0.4)), paperc.inputs[0])
c1 = node('ShaderNodeMix', data_type='RGBA'); L.new(black, c1.inputs[0]); L.new(paperc.outputs[2], c1.inputs[6]); c1.inputs[7].default_value = (0.006, 0.006, 0.006, 1)
c2 = node('ShaderNodeMix', data_type='RGBA'); L.new(mathn('MULTIPLY', redk, 0.97, clamp=True), c2.inputs[0]); L.new(c1.outputs[2], c2.inputs[6]); c2.inputs[7].default_value = (0.55, 0.0, 0.012, 1)
# 压痕：章压下时纸凹下去，带褶皱
sepV = node('ShaderNodeSeparateXYZ'); L.new(m3.outputs['Vector'], sepV.inputs['Vector'])
rx = mathn('MULTIPLY', mathn('SUBTRACT', sepV.outputs['X'], 0.5), 1.5); ry = mathn('MULTIPLY', mathn('SUBTRACT', sepV.outputs['Y'], 0.5), 1.5)
dist = mathn('SQRT', mathn('ADD', mathn('MULTIPLY', rx, rx), mathn('MULTIPLY', ry, ry)))
dm = node('ShaderNodeMapRange'); dm.inputs['From Min'].default_value = 0.35; dm.inputs['From Max'].default_value = 0.95; dm.inputs['To Min'].default_value = 1.0; dm.inputs['To Max'].default_value = 0.0; dm.clamp = True; L.new(dist, dm.inputs['Value'])
dent_h = mathn('MULTIPLY', mathn('MULTIPLY', dm.outputs['Result'], dent.outputs[0]), mathn('ADD', mathn('MULTIPLY', wrk.outputs['Fac'], 1.2), 0.5))
bump = node('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.6; bump.inputs['Distance'].default_value = 0.0006
hs = mathn('SUBTRACT', mathn('ADD', mathn('MULTIPLY', fib.outputs['Fac'], 0.8), mathn('MULTIPLY', mathn('ADD', black, redk), -0.25)), mathn('MULTIPLY', dent_h, 3.0)); L.new(hs, bump.inputs['Height'])
lw = node('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.45
shade = mathn('SUBTRACT', 1.0, mathn('MULTIPLY', lw.outputs['Facing'], 0.5))
sg = node('ShaderNodeCombineColor'); L.new(shade, sg.inputs[0]); L.new(shade, sg.inputs[1]); L.new(shade, sg.inputs[2])
fin = node('ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); fin.inputs[0].default_value = 1.0; L.new(c2.outputs[2], fin.inputs[6]); L.new(sg.outputs[0], fin.inputs[7])
# 边缘/薄处透光：边缘 e=|u-0.5|*2 的 4 次方；中间只有少量
uvx = node('ShaderNodeSeparateXYZ'); L.new(tc_.outputs['UV'], uvx.inputs['Vector'])
e_ = mathn('POWER', mathn('MULTIPLY', mathn('ABSOLUTE', mathn('SUBTRACT', uvx.outputs['X'], 0.5)), 2.0), 4.0, clamp=True)
slot_t = mathn('POWER', mathn('SUBTRACT', 1.0, mathn('DIVIDE', rigz, 0.014), clamp=True), 3.0)
amber = node('ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); L.new(mathn('ADD', 0.12, mathn('MULTIPLY', e_, 0.88), clamp=True), amber.inputs[0]); L.new(fin.outputs[2], amber.inputs[6]); amber.inputs[7].default_value = (1.0, 0.62, 0.30, 1)
bsdf = node('ShaderNodeBsdfPrincipled'); L.new(fin.outputs[2], bsdf.inputs['Base Color'])
rough = mathn('SUBTRACT', 0.66, mathn('MULTIPLY', mathn('MULTIPLY', mk, wet.outputs[0]), 0.5))
L.new(rough, bsdf.inputs['Roughness']); setin(bsdf, ['Specular IOR Level', 'Specular'], 0.3); setin(bsdf, 'Sheen Weight', 0.3); L.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
tr = node('ShaderNodeBsdfTranslucent'); L.new(amber.outputs[2], tr.inputs['Color']); L.new(bump.outputs['Normal'], tr.inputs['Normal'])
mx = node('ShaderNodeMixShader'); L.new(mathn('ADD', 0.16, mathn('MULTIPLY', e_, 0.6)), mx.inputs['Fac']); L.new(bsdf.outputs['BSDF'], mx.inputs[1]); L.new(tr.outputs['BSDF'], mx.inputs[2])
em = node('ShaderNodeEmission'); em.inputs['Color'].default_value = (1.0, 0.52, 0.18, 1)
glow = mathn('MAXIMUM', mathn('MULTIPLY', e_, env('EDGE', 2.0)), mathn('MULTIPLY', slot_t, env('SLOT', 1.5)))
L.new(mathn('MULTIPLY', glow, mathn('SUBTRACT', 1.0, mathn('MAXIMUM', black, redk), clamp=True)), em.inputs['Strength'])
ad = node('ShaderNodeAddShader'); L.new(mx.outputs['Shader'], ad.inputs[0]); L.new(em.outputs['Emission'], ad.inputs[1])
o = node('ShaderNodeOutputMaterial'); L.new(ad.outputs['Shader'], o.inputs['Surface'])
paper.data.materials.append(pm)
VAL = {n: N[n].outputs[0] for n in ('zoff', 'prog', 'presence', 'bleed', 'wet', 'dent')}

# ---- 出纸口：深色塑料面板 + 拉丝金属前沿 + 齿状撕纸刃 + 螺丝 ----
bpy.ops.mesh.primitive_cube_add(size=1); lip = bpy.context.object; lip.scale = (0.10, 0.006, 0.0466); lip.location = (0, -0.0075, -0.0268)
bpy.ops.object.transform_apply(scale=True); adopt(lip)
bv = lip.modifiers.new('b', 'BEVEL'); bv.width = 0.0012; bv.segments = 4; bpy.ops.object.shade_smooth()
lip.data.materials.append(newmat('lip', (0.012, 0.012, 0.014, 1), 0.38))
bpy.ops.mesh.primitive_cube_add(size=1); edge = bpy.context.object; edge.scale = (0.10, 0.0066, 0.0034); edge.location = (0, -0.0075, -0.0017)
bpy.ops.object.transform_apply(scale=True); adopt(edge); eb = edge.modifiers.new('b', 'BEVEL'); eb.width = 0.0010; eb.segments = 5; bpy.ops.object.shade_smooth()
em_ = newmat('edgemetal', (0.22, 0.22, 0.24, 1), 0.34, 1.0); en = em_.node_tree
etc = en.nodes.new('ShaderNodeTexCoord'); emp = en.nodes.new('ShaderNodeMapping'); emp.inputs['Scale'].default_value = (3, 1, 1400)
ens = en.nodes.new('ShaderNodeTexNoise'); ens.inputs['Detail'].default_value = 3; ebp = en.nodes.new('ShaderNodeBump'); ebp.inputs['Strength'].default_value = 0.5; ebp.inputs['Distance'].default_value = 0.0002
en.links.new(etc.outputs['Object'], emp.inputs['Vector']); en.links.new(emp.outputs['Vector'], ens.inputs['Vector']); en.links.new(ens.outputs['Fac'], ebp.inputs['Height'])
en.links.new(ebp.outputs['Normal'], en.nodes['Principled BSDF'].inputs['Normal']); edge.data.materials.append(em_)
# 撕纸刃：三角齿，齿距 1.2 mm
NT = 76; pt = 0.0012; x0 = -NT*pt/2
tv = [(x0, -0.0010)] ; tv += [(x0+i*pt, 0.0 if i % 2 == 0 else 0.0013) for i in range(NT+1)]; tv += [(x0+NT*pt, -0.0010)]
tm_ = bpy.data.meshes.new('teeth'); tm_.from_pydata([(x, 0, z) for x, z in tv], [], [tuple(range(len(tv)))]); tm_.update()
teeth = bpy.data.objects.new('teeth', tm_); sc.collection.objects.link(teeth); adopt(teeth); teeth.location = (0, -0.0042, 0.0)
ts = teeth.modifiers.new('s', 'SOLIDIFY'); ts.thickness = 0.0016; teeth.data.materials.append(em_)
for sx in (-0.038, 0.038):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.0021, depth=0.0010); sb = bpy.context.object
    sb.rotation_euler = (math.pi/2, 0, 0); sb.location = (sx, -0.0107, -0.016); adopt(sb); sb.data.materials.append(em_)

# ---- 章：黑木块 + 红胶面 + 圆钮 ----
stamp = bpy.data.objects.new('stamp', None); sc.collection.objects.link(stamp); adopt(stamp)
def part(kind, loc, scale, mat, rot=(0, 0, 0), bevel=0.0007):
    if kind == 'cube': bpy.ops.mesh.primitive_cube_add(size=1)
    else: bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.5, depth=1)
    ob = bpy.context.object; ob.scale = scale; ob.location = loc; ob.rotation_euler = rot; bpy.ops.object.transform_apply(scale=True, rotation=True)
    b = ob.modifiers.new('b', 'BEVEL'); b.width = bevel; b.segments = 4; bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat); ob.parent = stamp; return ob
rubber = newmat('rubber', (0.40, 0.0, 0.01, 1), 0.85); wood = newmat('wood', (0.03, 0.026, 0.024, 1), 0.34)
part('cube', (0, -0.0015, 0), (0.0275, 0.003, 0.0140), rubber, bevel=0.0004)
part('cube', (0, -0.0140, 0), (0.0245, 0.020, 0.0115), wood, bevel=0.0012)
part('cyl', (0, -0.0340, 0), (0.011, 0.020, 0.011), wood, rot=(math.pi/2, 0, 0), bevel=0.0020)

# ---- 背景光斑：多层次、暗、大小不一；中心亮边缘衰减 ----
rnd = random.Random(11)
def bokeh_mat(name, col, strength):
    m = bpy.data.materials.new(name); m.use_nodes = True; n_ = m.node_tree; n_.nodes.clear()
    e = n_.nodes.new('ShaderNodeEmission'); e.inputs['Color'].default_value = col
    lw_ = n_.nodes.new('ShaderNodeLayerWeight'); lw_.inputs['Blend'].default_value = 0.5
    mm = n_.nodes.new('ShaderNodeMath'); mm.operation = 'MULTIPLY_ADD'; mm.inputs[1].default_value = -0.85; mm.inputs[2].default_value = 1.0
    ms = n_.nodes.new('ShaderNodeMath'); ms.operation = 'MULTIPLY'; ms.inputs[1].default_value = strength
    n_.links.new(lw_.outputs['Facing'], mm.inputs[0]); n_.links.new(mm.outputs[0], ms.inputs[0]); n_.links.new(ms.outputs[0], e.inputs['Strength'])
    o_ = n_.nodes.new('ShaderNodeOutputMaterial'); n_.links.new(e.outputs[0], o_.inputs['Surface']); return m
BK = env('BOKEH', 14)
tiers = [bokeh_mat('bk_hi', (1.0, 0.55, 0.18, 1), BK*1.6), bokeh_mat('bk_mid', (1.0, 0.62, 0.25, 1), BK), bokeh_mat('bk_lo', (0.95, 0.45, 0.15, 1), BK*0.45), bokeh_mat('bk_cool', (0.85, 0.92, 1.0, 1), BK*0.7)]
for k in range(64):
    rad = rnd.choice([0.0008, 0.0012, 0.0016, 0.0022, 0.003]); yv = rnd.uniform(0.25, 1.1)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=rad*(0.5+yv), segments=24, ring_count=12)
    ob = bpy.context.object; ob.location = (rnd.uniform(-0.3, 0.3)*(0.3+yv), yv, rnd.uniform(-0.12, 0.20))
    ob.data.materials.append(tiers[3] if k % 9 == 0 else tiers[0] if k % 11 == 0 else tiers[2] if k % 3 else tiers[1])

# ---- 灯：真逆光（暖，隔着纸透）+ 很弱的侧前光托纤维 + 前沿高光 ----
def mk_light(kind, name):
    l = bpy.data.lights.new(name, kind); ob = bpy.data.objects.new(name, l); sc.collection.objects.link(ob); return ob
def aim(ob, tgt): ob.rotation_euler = (Vector(tgt) - ob.location).to_track_quat('-Z', 'Y').to_euler()
back = mk_light('AREA', 'back'); back.data.shape = 'RECTANGLE'; back.data.size = 0.03; back.data.size_y = 0.06
back.location = (0.02, 0.035, 0.03); aim(back, (0, -1, 0.03)); back.rotation_euler = (math.radians(-90), 0, 0); back.data.color = (1.0, 0.58, 0.26); adopt(back)
key = mk_light('SPOT', 'key'); key.data.spot_size = math.radians(30); key.data.spot_blend = 0.8; key.data.shadow_soft_size = 0.02
key.location = (-0.16, -0.12, 0.09); aim(key, (0.0, 0, 0.018)); key.data.color = (1.0, 0.9, 0.78); adopt(key)
hl = mk_light('AREA', 'edgehl'); hl.data.shape = 'RECTANGLE'; hl.data.size = 0.09; hl.data.size_y = 0.004; hl.data.color = (1.0, 0.85, 0.65)
hl.location = (0, -0.05, 0.03); hl.rotation_euler = (Vector((0, 0.0075, 0.0)) - hl.location).to_track_quat('-Z', 'Y').to_euler(); adopt(hl)
back.data.energy = env('BACK', 0.022); key.data.energy = env('KEY', 1.1); hl.data.energy = 0.02

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cd = cam.data; cd.sensor_fit = 'HORIZONTAL'; cd.sensor_width = 36; cd.lens = 85
cd.dof.use_dof = True; cd.dof.aperture_fstop = 9.0

def eo3(x): x = min(1, max(0, x)); return 1-(1-x)**3
def eio(x): x = min(1, max(0, x)); return x*x*(3-2*x)
def lerp(a, b, k): return a+(b-a)*k
def off(t):
    s = 0.0
    for te, rows, n in EVENTS:
        for k in range(n): s += rows*P/n*eo3((t-(te+k*0.09))/0.07)
    return s
def progv(t):
    v = 0.0
    for t0, t1, a0, a1 in PROG:
        if t >= t0: v = lerp(a0, a1, min(1, (t-t0)/(t1-t0)))
    return v
def setframe(i):
    t = i/30.0
    tau = t-TC; push = 0.0
    if 0 <= tau < 0.06: push = 0.0022*min(1, tau/0.025)
    elif tau >= 0.06:
        q = tau-0.06; push = 0.0022*math.exp(-9*q)*math.cos(26*q)
    paper.location = (0, push, Z0 + off(t))
    rig.rotation_euler = (RIG_ROT[0] + math.radians(1.2*math.sin(t*1.1)), RIG_ROT[1] + math.radians(1.0*math.sin(t*1.7+1)), RIG_ROT[2] + math.radians(1.5*math.sin(t*0.8)))
    mz = paper.location.z - (TM + MARK_ROW*P)
    s = 0.05; lat = Vector((0.0, 0.0)); tilt = 0.0; vis = False
    if TC-0.35 <= t < TC:
        a_ = (t-(TC-0.35))/0.35; s = 0.05*(1-a_**3)+0.0005; lat = Vector((0.08, 0.04))*(1-a_)**2; vis = True
    elif TC <= t < TC+0.05: s = 0.0004; vis = True
    elif TC+0.05 <= t < TC+0.22:
        b = (t-(TC+0.05))/0.17; s = 0.05*b**1.5+0.0004; lat = Vector((0.10, 0.06))*b**1.6; tilt = 0.35*b; vis = True
    for ob_ in [stamp]+list(stamp.children): ob_.hide_render = not vis
    stamp.location = (MARK_DX+lat.x, -s+push, mz+lat.y); stamp.rotation_euler = (tilt, 0, math.radians(MARK_ROT))
    VAL['zoff'].default_value = paper.location.z
    VAL['presence'].default_value = 1.0 if t >= TC else 0.0
    VAL['bleed'].default_value = eo3((t-TC)/0.40)
    VAL['wet'].default_value = math.exp(-(t-TC)/1.8) if t >= TC else 0.0
    VAL['dent'].default_value = max(0.0, push/0.0022) if t >= TC else 0.0
    VAL['prog'].default_value = progv(t)
    # 相机：偏低偏侧，沿纸面缓缓跟、缓缓推近；跟着章落下和走纸的位置
    tz = 0.0195 + 0.003*t/8.0
    tgt = rig.matrix_world @ Vector((0.0, 0.0, tz))
    zoom = 1.0 + 0.06*eio((t-1.5)/2.0) + 0.06*eio((t-6.3)/1.3)
    az = math.radians(-20 + 10*t/8.0 + 2.0*math.sin(t*0.9)); el = math.radians(-5 + 4*math.sin(t*0.55))
    d = 0.170/zoom
    sh = 0.0012*math.exp(-12*tau)*math.sin(80*tau) if 0 <= tau < 0.6 else 0.0           # 章落下，镜头一震
    cam.location = tgt + Vector((d*math.sin(az)*math.cos(el) + sh, -d*math.cos(az)*math.cos(el), d*math.sin(el) + 0.8*sh))
    aim(cam, tgt); cd.dof.focus_distance = d

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
                     ('use_soft_shadows', True), ('use_motion_blur', True), ('motion_blur_shutter', 0.5), ('bloom_threshold', 1.0), ('bloom_intensity', 0.15), ('bokeh_max_size', 200)):
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
