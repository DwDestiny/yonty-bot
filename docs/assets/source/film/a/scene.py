# Input: assets 目录（NotoSansSC.ttf、studio_small_09_1k.hdr）；Output: PNG 帧；Pos: 方向一「黑曜」样片场景（Blender Cycles）
# blender -b -P scene.py -- DEVICE FRAMES OUTDIR SAMPLES DENOISE ASSETDIR [RES%]
# DEVICE: CPU|METAL   FRAMES: 0 或 0,90,236 或 0-239   字体 Noto Sans SC（OFL）；HDRI Poly Haven studio_small_09（CC0）
import bpy, sys, math, time, os, random
from mathutils import Vector

a = sys.argv[sys.argv.index('--') + 1:]
dev, frames, out, samples, dn, assets = a[:6]
pct = int(a[6]) if len(a) > 6 else 100
fl = []
for part in frames.split(','):
    if '-' in part:
        x, y = part.split('-'); fl += list(range(int(x), int(y) + 1))
    else:
        fl.append(int(part))
samples = int(samples); dn = int(dn)
FPS = 30; NF = 240

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; r = sc.render
r.resolution_x = 1280; r.resolution_y = 720; r.resolution_percentage = pct; r.fps = FPS
r.image_settings.file_format = 'PNG'; r.image_settings.color_depth = '16'
sc.frame_start = 0; sc.frame_end = NF - 1
try: sc.view_settings.view_transform = 'AgX'
except Exception: sc.view_settings.view_transform = 'Filmic'
for lk in ('AgX - High Contrast', 'High Contrast'):
    try: sc.view_settings.look = lk; break
    except Exception: pass
r.engine = 'CYCLES'; c = sc.cycles; c.samples = samples; c.use_denoising = bool(dn)
c.max_bounces = 8; c.caustics_reflective = False; c.caustics_refractive = False; c.sample_clamp_indirect = 10
r.use_motion_blur = True; r.motion_blur_shutter = 0.5
if dev == 'METAL':
    p = bpy.context.preferences.addons['cycles'].preferences; p.compute_device_type = 'METAL'; p.get_devices()
    for d in p.devices: d.use = True
    c.device = 'GPU'
else:
    c.device = 'CPU'
if dn:
    try: c.denoiser = 'OPENIMAGEDENOISE'
    except Exception: pass

# ---------- 缓动和时间表 ----------
def cl(x, lo=0.0, hi=1.0): return min(hi, max(lo, x))
def seg(t, a0, b0): return cl((t - a0) / (b0 - a0))
def p2out(u): return 1 - (1 - u) ** 2
def p2in(u): return u * u
def p3in(u): return u ** 3
def p2io(u): return 2 * u * u if u < 0.5 else 1 - 2 * (1 - u) ** 2
def expo_out(u): return 1.0 if u >= 1 else 1 - 2 ** (-10 * u)
def back_out(u, s=1.2): u -= 1; return u * u * ((s + 1) * u + s) + 1
def sstep(u): return u * u * (3 - 2 * u)
def inv_p2io(p):
    lo, hi = 0.0, 1.0
    for _ in range(50):
        m = (lo + hi) / 2
        if p2io(m) < p: lo = m
        else: hi = m
    return (lo + hi) / 2

GX = (-0.6, 0.0, 0.6)           # 做 完 了 的 x
BAR_X0, BAR_X1 = -1.3, 1.3
HIT = 2.8                       # 第一遍扫光到“了”的时刻（红裂纹出现）
D1 = 1.4                        # 第一遍扫光时长
u_le = inv_p2io((GX[2] - BAR_X0) / (BAR_X1 - BAR_X0))
S1 = HIT - u_le * D1            # 第一遍起扫时刻（按缓动反解，约 1.87 s）
S2, D2 = 6.6, 1.0               # 第二遍
def sweep_x(t, s, d): return BAR_X0 + (BAR_X1 - BAR_X0) * p2io(seg(t, s, s + d))
def pass_t(x, s, d): return s + d * inv_p2io((x - BAR_X0) / (BAR_X1 - BAR_X0))
BACK = 4.5                      # 退回时牌往后走的距离

# ---------- 世界：反射用 HDRI，相机看到的是暗蓝渐变 ----------
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
env = nt.nodes.new('ShaderNodeTexEnvironment'); env.image = bpy.data.images.load(os.path.join(assets, 'studio_small_09_1k.hdr'))
mp = nt.nodes.new('ShaderNodeMapping'); mp.inputs['Rotation'].default_value = (0, 0, 2.2); tc = nt.nodes.new('ShaderNodeTexCoord')
bgE = nt.nodes.new('ShaderNodeBackground'); bgE.inputs['Strength'].default_value = 0.05
win = nt.nodes.new('ShaderNodeSeparateXYZ'); ramp = nt.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1); ramp.color_ramp.elements[0].position = 0.28; ramp.color_ramp.elements[1].color = (0.014, 0.024, 0.055, 1)
bgK = nt.nodes.new('ShaderNodeBackground')
lp = nt.nodes.new('ShaderNodeLightPath'); mix = nt.nodes.new('ShaderNodeMixShader'); outn = nt.nodes.new('ShaderNodeOutputWorld')
nt.links.new(tc.outputs['Generated'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], env.inputs['Vector']); nt.links.new(env.outputs['Color'], bgE.inputs['Color'])
nt.links.new(tc.outputs['Window'], win.inputs['Vector']); nt.links.new(win.outputs['Y'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], bgK.inputs['Color'])
nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac']); nt.links.new(bgE.outputs['Background'], mix.inputs[1]); nt.links.new(bgK.outputs['Background'], mix.inputs[2]); nt.links.new(mix.outputs['Shader'], outn.inputs['Surface'])

# ---------- 材质 ----------
FADE = []   # 所有带“淡出到雾里”的材质的 fade 插槽
def principled(m, **k):
    b = m.node_tree.nodes['Principled BSDF']
    for n, v in k.items():
        if n in b.inputs: b.inputs[n].default_value = v
    return b
def fadeable(m, shader_out, name):
    """shader_out: 一个着色器输出口；返回 fade 插槽（0=实体 1=全透明）"""
    nt = m.node_tree; tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mx = nt.nodes.new('ShaderNodeMixShader')
    outn = nt.nodes['Material Output']
    nt.links.new(shader_out, mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], outn.inputs['Surface'])
    mx.inputs['Fac'].default_value = 0.0; FADE.append(mx.inputs['Fac']); return mx.inputs['Fac']
def emit_mat(name, color, strength, fade=True):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n)
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*color, 1); em.inputs['Strength'].default_value = strength
    if fade: fadeable(m, em.outputs[0], name)
    else: nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    return m, em

AMBER = (1.0, 0.50, 0.12); COLD = (0.80, 0.90, 1.0); RED = (1.0, 0.025, 0.01)

G = bpy.data.objects.new('G', None); sc.collection.objects.link(G)       # 牌的整体（一起退、一起回）
def child(o): o.parent = G; return o

CW, CH, CT = 2.2, 1.1, 0.12; CZ = 0.62
bpy.ops.mesh.primitive_cube_add(size=1); card = bpy.context.object; card.scale = (CW, CT, CH); bpy.ops.object.transform_apply(scale=True)
card.location = (0, 0, CZ)
bv = card.modifiers.new('b', 'BEVEL'); bv.width = 0.035; bv.segments = 8; bpy.ops.object.shade_smooth(); child(card)
cm = bpy.data.materials.new('obsidian'); cm.use_nodes = True
principled(cm, **{'Base Color': (0.006, 0.008, 0.014, 1), 'Roughness': 0.08, 'Metallic': 0.0, 'Specular IOR Level': 1.0, 'Coat Weight': 1.0, 'Coat Roughness': 0.03})
FADE_CARD = fadeable(cm, cm.node_tree.nodes['Principled BSDF'].outputs[0], 'obsidian'); card.data.materials.append(cm)

# 牌边发光层：比牌略大、放在牌背后，露出一圈边
bpy.ops.mesh.primitive_cube_add(size=1); edge = bpy.context.object; edge.scale = (CW + 0.03, 0.02, CH + 0.03); bpy.ops.object.transform_apply(scale=True)
edge.location = (0, CT / 2 - 0.005, CZ); child(edge)
em_edge, edge_node = emit_mat('edge', COLD, 0.0); edge.data.materials.append(em_edge)

font = bpy.data.fonts.load(os.path.join(assets, 'NotoSansSC.ttf'))
def mktext(body, size, x, z, y, mat, extrude=0.0, bevel=0.0, offset=0.0, parent=True, name='t'):
    bpy.ops.object.text_add(); o = bpy.context.object; o.name = name; d = o.data
    d.body = body; d.font = font; d.size = size; d.align_x = 'CENTER'; d.align_y = 'CENTER'
    d.extrude = extrude; d.bevel_depth = bevel; d.bevel_resolution = 2; d.offset = offset
    o.rotation_euler = (math.pi / 2, 0, 0); o.location = (x, y, z); o.data.materials.append(mat)
    if parent: child(o)
    return o
# 牌上的字：挤出几何，深 0.03，倒角
FY = -CT / 2 - 0.016
glyph = []
for ch, gx in zip('做完了', GX):
    m, em = emit_mat('g_' + ch, AMBER, 5.0)
    o = mktext(ch, 0.66, gx, CZ + 0.0, FY, m, extrude=0.012, bevel=0.007, offset=0.0, name='glyph_' + ch)
    glyph.append((o, m, em))
# 牌面蚀刻小字“示意”
m_et, em_et = emit_mat('etch', COLD, 0.55)
mktext('示意 · 任务#3', 0.065, -0.62, CZ - 0.44, -CT / 2 - 0.004, m_et, name='etch')

# 红裂纹：折线曲线，bevel_factor_end 长出来
cv = bpy.data.curves.new('crack', 'CURVE'); cv.dimensions = '3D'; cv.bevel_depth = 0.007; cv.bevel_resolution = 1
sp = cv.splines.new('POLY'); pts = [(0.64, 0.98), (0.57, 0.86), (0.66, 0.76), (0.55, 0.66), (0.63, 0.56), (0.53, 0.45), (0.60, 0.36), (0.55, 0.26)]
sp.points.add(len(pts) - 1)
for pt, (x, z) in zip(sp.points, pts): pt.co = (x, 0, z, 1)
crack = bpy.data.objects.new('crack', cv); sc.collection.objects.link(crack); crack.location = (0, FY - 0.014, 0); child(crack)
m_cr, em_cr = emit_mat('crack', RED, 0.0); cv.materials.append(m_cr); cv.bevel_factor_start = 0.0; cv.bevel_factor_end = 0.0

# 小标签（在牌外面，不跟牌退；各自淡入淡出）
LABELS = {}
def label(key, body, size, x, z, color, strength):
    m, em = emit_mat('l_' + key, color, 0.0, fade=False)
    o = mktext(body, size, x, z, -0.2, m, extrude=0.0, bevel=0.003, offset=0.0, parent=False, name='lab_' + key)
    LABELS[key] = (o, em, strength, x, z)
label('rerun', '复跑 make check', 0.14, 0.0, 1.58, COLD, 1.6)
label('back', '退回', 0.16, 0.0, 1.58, (1.0, 0.82, 0.78), 1.4)
label('rework', '返工 1', 0.18, 0.0, CZ, COLD, 1.0)
label('pass', 'PASS', 0.2, 0.0, 1.58, COLD, 3.0)

# 扫光条 + 灯
bpy.ops.mesh.primitive_cube_add(size=1); bar = bpy.context.object; bar.scale = (0.014, 0.03, 1.5); bpy.ops.object.transform_apply(scale=True)
bar.location = (BAR_X0, -0.15, 0.68)
m_bar, em_bar = emit_mat('bar', (0.78, 0.9, 1.0), 0.0, fade=False); bar.data.materials.append(m_bar)
bl = bpy.data.lights.new('barlight', 'AREA'); bl.shape = 'RECTANGLE'; bl.size = 0.04; bl.size_y = 1.5; bl.color = (0.75, 0.88, 1.0); bl.energy = 0
barlight = bpy.data.objects.new('barlight', bl); sc.collection.objects.link(barlight); barlight.rotation_euler = (math.pi / 2, 0, 0)

# 地面：60 米大平面，反射和高光随离牌距离衰减；脚下一圈暖光
bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0)); floor = bpy.context.object
fm = bpy.data.materials.new('floor'); fm.use_nodes = True; fn = fm.node_tree; fb = fn.nodes['Principled BSDF']
tcf = fn.nodes.new('ShaderNodeTexCoord'); vl = fn.nodes.new('ShaderNodeVectorMath'); vl.operation = 'LENGTH'
fn.links.new(tcf.outputs['Object'], vl.inputs[0])
def maprange(a0, b0, c0, d0, link_from):
    n = fn.nodes.new('ShaderNodeMapRange'); n.inputs['From Min'].default_value = a0; n.inputs['From Max'].default_value = b0
    n.inputs['To Min'].default_value = c0; n.inputs['To Max'].default_value = d0; n.clamp = True
    fn.links.new(link_from, n.inputs['Value']); return n
fn.links.new(maprange(0.0, 1.8, 0.04, 0.45, vl.outputs['Value']).outputs['Result'], fb.inputs['Roughness'])
fn.links.new(maprange(0.1, 1.3, 0.8, 0.0, vl.outputs['Value']).outputs['Result'], fb.inputs['Specular IOR Level'])
fb.inputs['Base Color'].default_value = (0.004, 0.005, 0.009, 1)
ring = maprange(0.0, 1.6, 1.0, 0.0, vl.outputs['Value']); sq = fn.nodes.new('ShaderNodeMath'); sq.operation = 'POWER'; sq.inputs[1].default_value = 3.0
fn.links.new(ring.outputs['Result'], sq.inputs[0])
fn.links.new(sq.outputs['Value'], fb.inputs['Emission Strength']); fb.inputs['Emission Color'].default_value = (*AMBER, 1)
fb.inputs['Emission Strength'].default_value = 0.0
# Emission Strength 由链接给出：乘 0.7
mul = fn.nodes.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'; mul.inputs[1].default_value = 1.1
fn.links.new(sq.outputs['Value'], mul.inputs[0]); fn.links.new(mul.outputs['Value'], fb.inputs['Emission Strength'])
floor.data.materials.append(fm)

# 灯：左侧竖条主光（给牌左倒角和上沿一条细高光）、背后上方顶光条、右后冷色轮廓光
def mkarea(name, loc, tgt, sx, sy, energy, color=(1, 1, 1)):
    l = bpy.data.lights.new(name, 'AREA'); l.shape = 'RECTANGLE'; l.size = sx; l.size_y = sy; l.energy = energy; l.color = color
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o); o.location = loc
    o.rotation_euler = (Vector(tgt) - o.location).to_track_quat('-Z', 'Y').to_euler(); return o
mkarea('keystrip', (-3.2, -1.2, 0.9), (0, 0, CZ), 0.12, 1.8, 800, (0.95, 0.97, 1.0))
mkarea('topstrip', (0.4, 1.0, 2.6), (0, 0, CZ), 1.8, 0.12, 300, (0.9, 0.95, 1.0))
mkarea('rim', (2.8, 1.4, 1.0), (0, 0, CZ), 0.4, 1.2, 140, (0.46, 0.62, 1.0))

# 尘点：30 颗，景深里糊成光斑
random.seed(7)
m_du, em_du = emit_mat('dust', (1.0, 0.75, 0.5), 2.0, fade=False)
for k in range(30):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.009, segments=8, ring_count=6, location=(random.uniform(-2.8, 2.8), random.uniform(-1.6, 2.5), random.uniform(0.15, 2.0)))
    bpy.context.object.data.materials.append(m_du)

# 摄像机
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cd = cam.data; cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 24; cd.lens = 12 / math.tan(math.radians(16)); cd.dof.use_dof = True; cd.dof.aperture_fstop = 3.0
CAM_Z = 0.62; AIM_Z = 0.74

def lab_vis(key, t, a0, b0, fin=0.2, fout=0.11):
    return cl((t - a0) / fin) * (1 - cl((t - (b0 - fout)) / fout)) if a0 <= t <= b0 else 0.0

def setframe(i):
    """写关键帧：整条时间线都在这里，渲染时 frame_set 取值（运动模糊靠相邻帧的变换）"""
    t = i / FPS
    kf = lambda owner, path, **k: owner.keyframe_insert(path, frame=i, **k)
    # --- 牌的退回 / 回来 ---
    u = seg(t, 3.3, 4.2); v = seg(t, 5.0, 6.6)
    if t < 5.0: y = BACK * p3in(u); fade = u ** 1.5
    else:
        e = expo_out(v); y = BACK * (1 - e); fade = 1 - cl(e * 1.15)
    G.location = (0, y, 0); kf(G, 'location')
    for s in FADE: s.default_value = 0.0
    for s in FADE_CARD, *[g[2].id_data.nodes['Mix Shader'].inputs['Fac'] for g in glyph]: s.default_value = fade; s.keyframe_insert('default_value', frame=i)
    # 其它 fadeable 材质（边、牌上蚀刻、裂纹）：同步
    for mm in (em_edge, m_et, m_cr):
        sk = [n for n in mm.node_tree.nodes if n.type == 'MIX_SHADER'][0].inputs['Fac']; sk.default_value = fade; sk.keyframe_insert('default_value', frame=i)
    # --- 字光：琥珀；裂纹时降到 35%，退回时降到 15%；第二遍扫光过处变冷白 ---
    dim = 1.0
    if t >= HIT: dim = 1 - 0.65 * seg(t, HIT, HIT + 0.1)
    if t >= 3.3 and t < 5.0: dim = 0.35 - 0.20 * u
    if t >= 5.0: dim = 0.15 + 0.85 * seg(t, 5.0, 5.6)
    for (o, m, em), gx in zip(glyph, GX):
        cw = sstep(seg(t, pass_t(gx, S2, D2), pass_t(gx, S2, D2) + 0.12)) if t >= S2 else 0.0
        col = tuple(AMBER[k] * (1 - cw) + COLD[k] * cw for k in range(3))
        em.inputs['Color'].default_value = (*col, 1); em.inputs['Strength'].default_value = (5.0 + 1.6 * cw) * dim if cw == 0 else (5.0 + 1.6 * cw) * max(dim, 1.0 * (t > 5.6))
        em.inputs['Color'].keyframe_insert('default_value', frame=i); em.inputs['Strength'].keyframe_insert('default_value', frame=i)
    # 牌边亮起（第二遍）
    px = seg(t, S2, S2 + D2); es = 0.35 + 3.2 * sstep(px) if t >= S2 else 0.35
    edge_node.inputs['Strength'].default_value = es; edge_node.inputs['Strength'].keyframe_insert('default_value', frame=i)
    # --- 红裂纹 ---
    cg = expo_out(seg(t, HIT, HIT + 0.1)); cs = 1.4 * (1 - sstep(seg(t, 4.0, 4.15))) if t >= HIT else 0.0
    cv.bevel_factor_end = cg; cv.keyframe_insert('bevel_factor_end', frame=i)
    cs_ = 0.0001 if cs <= 0.001 else 1.0; crack.scale = (cs_, cs_, cs_); crack.keyframe_insert('scale', frame=i)
    em_cr.inputs['Strength'].default_value = cs; em_cr.inputs['Strength'].keyframe_insert('default_value', frame=i)
    # --- 扫光条 ---
    if t < S2 - 0.2:
        bx = BAR_X0 - 0.3 * (1 - p2out(seg(t, 1.0, 1.3))) if t < S1 else sweep_x(t, S1, D1)
        bon = cl((t - 1.0) / 0.25) * (1 - seg(t, 3.25, 3.5))
    else:
        bx = sweep_x(t, S2, D2); bon = cl((t - (S2 - 0.15)) / 0.15) * (1 - seg(t, S2 + D2, S2 + D2 + 0.25))
    bar.location = (bx, -0.15, 0.68); kf(bar, 'location'); bs = 1.0 if bon > 0.01 else 0.0001; bar.scale = (bs, bs, bs); kf(bar, 'scale')
    em_bar.inputs['Strength'].default_value = 6.0 * bon; em_bar.inputs['Strength'].keyframe_insert('default_value', frame=i)
    barlight.location = (bx, -0.55, 0.68); kf(barlight, 'location'); bl.energy = 90.0 * bon; bl.keyframe_insert('energy', frame=i)
    # --- 小标签 ---
    vis = {'rerun': lab_vis('rerun', t, 1.1, 3.3), 'back': lab_vis('back', t, 3.3, 4.3), 'rework': lab_vis('rework', t, 4.4, 4.9), 'pass': cl((t - 7.4) / 0.2)}
    for k, (o, em, st, lx, lz) in LABELS.items():
        em.inputs['Strength'].default_value = st * vis[k]; em.inputs['Strength'].keyframe_insert('default_value', frame=i)
        if k == 'rerun': o.location = (cl(bx, -0.55, 0.55), -0.2, lz)
        if k == 'pass':
            sc_ = 0.9 + 0.1 * back_out(cl((t - 7.4) / 0.2)); o.scale = (sc_, sc_, sc_)
        if k != 'pass': o.scale = (1, 1, 1) if vis[k] > 0.01 else (0.0001,) * 3
        if k == 'pass' and vis[k] <= 0.01: o.scale = (0.0001,) * 3
        kf(o, 'location'); kf(o, 'scale')
    # --- 摄像机：线性推轨；第二遍扫光时推进；撞击时抖一下 ---
    dist = 4.2 - 0.25 * cl(t / 5.0)
    if t >= 5.0: dist = 3.95
    if t >= S2: dist = 3.95 - 0.35 * p2io(seg(t, S2, S2 + 1.0))
    if t >= HIT: dist += 0.07 * math.exp(-(t - HIT) * 12) * math.sin((t - HIT) * 60 + 1.2) * 1.0 + 0.0
    camx = 0.5 * (1 - cl(t / 6.6)) * (1 - 0.0)
    cam.location = (camx, -dist, CAM_Z); tg = Vector((0, 0, AIM_Z))
    cam.rotation_euler = (tg - cam.location).to_track_quat('-Z', 'Y').to_euler(); cd.dof.focus_distance = dist
    kf(cam, 'location'); kf(cam, 'rotation_euler'); cd.dof.keyframe_insert('focus_distance', frame=i)

for i in range(NF): setframe(i)
for obj in bpy.data.objects:
    if obj.animation_data and obj.animation_data.action:
        for fc in obj.animation_data.action.fcurves: pass
res = []
os.makedirs(out, exist_ok=True)
print('S1', round(S1, 3), 'HIT', HIT, 'pass_t 做完了(1)', [round(pass_t(g, S1, D1), 3) for g in GX], '(2)', [round(pass_t(g, S2, D2), 3) for g in GX])
for i in fl:
    sc.frame_set(i); r.filepath = os.path.join(out, f'f{i:04d}.png'); a0 = time.time(); bpy.ops.render.render(write_still=True); res.append((i, round(time.time() - a0, 1)))
print('RESULT per-frame sec', res, 'blender', bpy.app.version_string)
