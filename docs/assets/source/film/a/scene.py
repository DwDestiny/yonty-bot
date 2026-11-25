# Input: assets 目录（NotoSansSC-Black.ttf、NotoSansSC.ttf、studio_small_09_1k.hdr）；Output: PNG 帧；Pos: 方向一「黑曜」样片场景（Blender Cycles，v2）
# blender -b -P scene.py -- DEVICE FRAMES OUTDIR SAMPLES DENOISE ASSETDIR [RES%]
# DEVICE: CPU|METAL   FRAMES: 0 或 0,90,236 或 0-239。字体 Noto Sans SC（OFL，Black 由可变字体实例化 wght=900）；HDRI Poly Haven studio_small_09（CC0）。
# 小字（复跑、退回、返工、PASS）不在这里做，见 post.py。
import bpy, bmesh, sys, math, time, os, random
from mathutils import Vector, Matrix, Quaternion

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
V5 = bpy.app.version >= (5, 0, 0)

def tryset(o, k, v):
    try: setattr(o, k, v)
    except Exception: pass
def use_nodes(d):
    if hasattr(d, 'use_nodes'):
        try: d.use_nodes = True
        except Exception: pass

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
sc.view_settings.exposure = 0.5
r.engine = 'CYCLES'; c = sc.cycles; c.samples = samples; c.use_denoising = bool(dn)
c.max_bounces = 8; c.caustics_reflective = False; c.caustics_refractive = False; c.sample_clamp_indirect = 10
c.volume_bounces = 0; tryset(c, 'volume_step_rate', 1.5); tryset(c, 'volume_max_steps', 96)
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

# ---------- 缓动和时间表（同 v1，扫光时刻按缓动反解） ----------
def cl(x, lo=0.0, hi=1.0): return min(hi, max(lo, x))
def seg(t, a0, b0): return cl((t - a0) / (b0 - a0))
def p2out(u): return 1 - (1 - u) ** 2
def p3in(u): return u ** 3
def p2io(u): return 2 * u * u if u < 0.5 else 1 - 2 * (1 - u) ** 2
def expo_out(u): return 1.0 if u >= 1 else 1 - 2 ** (-10 * u)
def sstep(u): return u * u * (3 - 2 * u)
def inv_p2io(p):
    lo, hi = 0.0, 1.0
    for _ in range(50):
        m = (lo + hi) / 2
        if p2io(m) < p: lo = m
        else: hi = m
    return (lo + hi) / 2

GX = (-0.58, 0.0, 0.58)         # 做 完 了 在牌面上的 x
BAR_X0, BAR_X1 = -1.35, 1.35
HIT = 2.8; D1 = 1.4
u_le = inv_p2io((GX[2] - BAR_X0) / (BAR_X1 - BAR_X0))
S1 = HIT - u_le * D1
S2, D2 = 6.6, 1.0
def sweep_x(t, s, d): return BAR_X0 + (BAR_X1 - BAR_X0) * p2io(seg(t, s, s + d))
def pass_t(x, s, d): return s + d * inv_p2io((x - BAR_X0) / (BAR_X1 - BAR_X0))
BACK = 4.5
YAW = math.radians(18)

# ---------- 世界：反射用 HDRI（冷色、很弱），相机看到近黑；低密度雾只被扫光灯照亮 ----------
w = bpy.data.worlds.new('w'); sc.world = w; use_nodes(w); nt = w.node_tree; nt.nodes.clear()
env = nt.nodes.new('ShaderNodeTexEnvironment'); env.image = bpy.data.images.load(os.path.join(assets, 'studio_small_09_1k.hdr'))
mp = nt.nodes.new('ShaderNodeMapping'); mp.inputs['Rotation'].default_value = (0, 0, 2.2); tc = nt.nodes.new('ShaderNodeTexCoord')
tint = nt.nodes.new('ShaderNodeMix'); tint.data_type = 'RGBA'; tint.blend_type = 'MULTIPLY'; tint.inputs[0].default_value = 1.0; tint.inputs[7].default_value = (0.55, 0.72, 1.0, 1)
bgE = nt.nodes.new('ShaderNodeBackground'); bgE.inputs['Strength'].default_value = 0.8
win = nt.nodes.new('ShaderNodeSeparateXYZ'); ramp = nt.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1); ramp.color_ramp.elements[0].position = 0.30; ramp.color_ramp.elements[1].color = (0.003, 0.005, 0.011, 1)
bgK = nt.nodes.new('ShaderNodeBackground')
lp = nt.nodes.new('ShaderNodeLightPath'); mix = nt.nodes.new('ShaderNodeMixShader'); outn = nt.nodes.new('ShaderNodeOutputWorld')
mixg = nt.nodes.new('ShaderNodeMixShader'); blk = nt.nodes.new('ShaderNodeBackground'); blk.inputs['Color'].default_value = (0, 0, 0, 1)
nt.links.new(tc.outputs['Generated'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], env.inputs['Vector'])
nt.links.new(env.outputs['Color'], tint.inputs[6]); nt.links.new(tint.outputs[2], bgE.inputs['Color'])
nt.links.new(tc.outputs['Window'], win.inputs['Vector']); nt.links.new(win.outputs['Y'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], bgK.inputs['Color'])
nt.links.new(lp.outputs['Is Glossy Ray'], mixg.inputs['Fac']); nt.links.new(blk.outputs['Background'], mixg.inputs[1]); nt.links.new(bgE.outputs['Background'], mixg.inputs[2])
nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac']); nt.links.new(mixg.outputs['Shader'], mix.inputs[1]); nt.links.new(bgK.outputs['Background'], mix.inputs[2]); nt.links.new(mix.outputs['Shader'], outn.inputs['Surface'])
vs = nt.nodes.new('ShaderNodeVolumeScatter'); vs.inputs['Density'].default_value = 0.10; vs.inputs['Anisotropy'].default_value = 0.6
nt.links.new(vs.outputs['Volume'], outn.inputs['Volume'])

# ---------- 材质 ----------
FADEKEYS = []   # (fade 插槽)：整体淡出到雾里
def new_mat(name):
    m = bpy.data.materials.new(name); use_nodes(m); return m
def with_fade(m, shader_out):
    nt = m.node_tree; tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mx = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(shader_out, mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    mx.inputs['Fac'].default_value = 0.0; FADEKEYS.append(mx.inputs['Fac']); return mx.inputs['Fac']
def emit_mat(name, color, strength, fade=True):
    m = new_mat(name); nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL': nt.nodes.remove(n)
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*color, 1); em.inputs['Strength'].default_value = strength
    if fade: with_fade(m, em.outputs[0])
    else: nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    return m, em
def obsidian(name):
    m = new_mat(name); b = m.node_tree.nodes['Principled BSDF']
    for k, v in {'Base Color': (0.006, 0.0075, 0.012, 1), 'Roughness': 0.12, 'Metallic': 0.0, 'Specular IOR Level': 1.0, 'Coat Weight': 1.0, 'Coat Roughness': 0.04}.items():
        if k in b.inputs: b.inputs[k].default_value = v
    with_fade(m, b.outputs[0]); return m

AMBER = (1.0, 0.50, 0.12); COLD = (0.80, 0.90, 1.0); RED = (1.0, 0.025, 0.01)
G = bpy.data.objects.new('G', None); sc.collection.objects.link(G); G.rotation_euler = (0, 0, YAW)   # 牌整体：一起退、一起回；绕竖轴转 18°
def child(o): o.parent = G; return o

CW, CH, CT = 2.2, 1.1, 0.18; CZ = 0.62
FACE_Y = -CT / 2
random.seed(11)

# ---------- 黑曜石牌：不规则崩口轮廓 + 贝壳状侧面 + 前缘斜切 ----------
def perimeter():
    W2, H2 = CW / 2, CH / 2
    chops = {'BL': (0.10, 0.08), 'BR': (0.17, 0.12), 'TR': (0.07, 0.15), 'TL': (0.13, 0.10)}   # (沿进入边, 沿离开边)
    corners = [('BL', (-W2, -H2)), ('BR', (W2, -H2)), ('TR', (W2, H2)), ('TL', (-W2, H2))]
    inward = [Vector((0, 1)), Vector((-1, 0)), Vector((0, -1)), Vector((1, 0))]
    pts = []
    for k in range(4):
        (na, A), (nb, B) = corners[k], corners[(k + 1) % 4]
        A = Vector(A); B = Vector(B); d = (B - A).normalized(); L = (B - A).length
        s0 = chops[na][1]; s1 = L - chops[nb][0]
        n = max(3, round((s1 - s0) / 0.12)); inn = inward[k]
        notch = random.sample(range(1, n), 2)
        edge = []
        for i in range(n + 1):
            t = s0 + (s1 - s0) * (i + (random.uniform(-0.25, 0.25) if 0 < i < n else 0)) / n
            edge.append([A + d * t, random.uniform(0, 0.006)])
        for ni in notch:
            dep = random.uniform(0.03, 0.06); edge[ni][1] += dep
            edge[ni - 1][1] += dep * 0.35; edge[ni + 1 if ni + 1 <= n else ni][1] += dep * 0.3
        for p, dd in edge: pts.append(p + inn * dd)
    return pts
def poly_normals(pts):
    n = len(pts); area = sum(pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y for i in range(n)) / 2
    sgn = 1 if area > 0 else -1; res = []
    for i in range(n):
        e1 = (pts[i] - pts[i - 1]).normalized(); e2 = (pts[(i + 1) % n] - pts[i]).normalized()
        n1 = Vector((e1.y, -e1.x)) * sgn; n2 = Vector((e2.y, -e2.x)) * sgn
        den = max(0.35, 1 + n1.dot(n2)); res.append((n1 + n2) / den)
    return res
def build_card():
    P = perimeter(); N = poly_normals(P); n = len(P)
    inset = lambda d: [p - nn * d for p, nn in zip(P, N)]
    jit = lambda: [p - nn * random.uniform(-0.014, 0.008) for p, nn in zip(P, N)]
    y0 = -CT / 2
    loops = [(inset(0.02), y0), (P, y0 + 0.022), (jit(), y0 + 0.07), (jit(), y0 + 0.12), (P, y0 + CT - 0.02), (inset(0.02), y0 + CT)]
    bm = bmesh.new(); vl = [[bm.verts.new((p.x, y, p.y)) for p in pts] for pts, y in loops]
    for k in range(len(vl) - 1):
        for i in range(n): bm.faces.new((vl[k][i], vl[k][(i + 1) % n], vl[k + 1][(i + 1) % n], vl[k + 1][i]))
    bm.faces.new(vl[0]); bm.faces.new(vl[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    me = bpy.data.meshes.new('card'); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new('card', me); sc.collection.objects.link(o); o.location = (0, 0, CZ); return o
card_a = build_card()

font_black = bpy.data.fonts.load(os.path.join(assets, 'NotoSansSC-Black.ttf'))
font_reg = bpy.data.fonts.load(os.path.join(assets, 'NotoSansSC.ttf'))
GSIZE = 0.64
def mktext(body, size, x, z, y, mat, fnt, extrude=0.0, bevel=0.0, name='t', parent=True):
    bpy.ops.object.text_add(); o = bpy.context.object; o.name = name; d = o.data
    d.body = body; d.font = fnt; d.size = size; d.align_x = 'CENTER'; d.align_y = 'CENTER'
    d.extrude = extrude; d.bevel_depth = bevel; d.resolution_u = 4
    o.rotation_euler = (math.pi / 2, 0, 0); o.location = (x, y, z)
    if mat is not None: d.materials.append(mat)
    if parent: child(o)
    return o
def to_mesh(o):
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.convert(target='MESH'); return bpy.context.object
def apply_mod(obj, name):
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=name)
def boolean_diff(obj, cutter):
    m = obj.modifiers.new('bool', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.operand_type = 'OBJECT'; m.object = cutter; m.solver = 'EXACT'
    tryset(m, 'use_self', True); apply_mod(obj, m.name)

# 1) 字槽：单字重 Black 的字当刀具，切进牌面 0.03（按牌宽折算约 12 毫米），槽口斜切。字刀是“脏”网格，所以放在裂纹布尔之后做
def cut_glyphs(obj):
    for ch, gx in zip('做完了', GX):
        cut = mktext(ch, GSIZE, gx, 0.0, FACE_Y, None, font_black, extrude=0.03, name='cut_' + ch, parent=False)
        cut.location = (gx, FACE_Y, CZ); cut = to_mesh(cut)
        cut.location = (gx, FACE_Y, CZ)
        boolean_diff(obj, cut); bpy.data.objects.remove(cut, do_unlink=True)
    bv = obj.modifiers.new('chamfer', 'BEVEL'); bv.width = 0.007; bv.segments = 1; bv.limit_method = 'ANGLE'; bv.angle_limit = math.radians(60)
    apply_mod(obj, bv.name)
cut_glyphs(card_a)
cmat = obsidian('obsidian'); card_a.data.materials.append(cmat); child(card_a)
FADE_CARD = [s for s in FADEKEYS][-1]

# 2) 裂开的牌：在槽牌基础上再切一道真裂（主裂两条加三条分叉，宽窄不一）
ORIGIN = Vector((0.60, -0.02))
LINES = [
    [ORIGIN, Vector((0.52, -0.20)), Vector((0.66, -0.31)), Vector((0.57, -0.44)), Vector((0.66, -0.55))],      # 主裂向下
    [ORIGIN, Vector((0.70, 0.12)), Vector((0.58, 0.26)), Vector((0.71, 0.40)), Vector((0.62, 0.55))],           # 主裂向上
    [Vector((0.70, 0.12)), Vector((0.88, 0.20)), Vector((1.01, 0.14)), Vector((1.10, 0.24))],                   # 分叉 1
    [Vector((0.52, -0.20)), Vector((0.36, -0.27)), Vector((0.24, -0.40))],                                      # 分叉 2
    [Vector((0.58, 0.26)), Vector((0.40, 0.33)), Vector((0.30, 0.47))],                                         # 分叉 3
]
WID = [(0.020, 0.003), (0.020, 0.003), (0.010, 0.002), (0.010, 0.002), (0.009, 0.002)]
CUTQ = []
def ribbon(line, w0, w1, bm_cut, bm_em, uvl, s_off):
    """每段一个凸四边形：刀具是凸棱柱（布尔稳），发光带同形，uv.x 是离裂缝起点的路程"""
    pts = [p if p is ORIGIN else p + Vector((random.uniform(-0.012, 0.012), random.uniform(-0.012, 0.012))) for p in line]
    L = [0.0]
    for i in range(1, len(pts)): L.append(L[-1] + (pts[i] - pts[i - 1]).length)
    tot = L[-1]; uvl_ = bm_em.loops.layers.uv.verify()
    for i in range(len(pts) - 1):
        d = (pts[i + 1] - pts[i]).normalized(); nn = Vector((-d.y, d.x))
        wa = (w0 + (w1 - w0) * L[i] / tot) / 2 * random.uniform(0.8, 1.2); wb = (w0 + (w1 - w0) * L[i + 1] / tot) / 2 * random.uniform(0.8, 1.2)
        q = [pts[i] + nn * wa, pts[i + 1] + nn * wb, pts[i + 1] - nn * wb, pts[i] - nn * wa]
        sv = [s_off + L[i], s_off + L[i + 1], s_off + L[i + 1], s_off + L[i]]
        CUTQ.append(q)
        fe = bm_em.faces.new([bm_em.verts.new((c.x, FACE_Y - 0.0006, c.y)) for c in q])
        for lp_, sx in zip(fe.loops, sv): lp_[uvl_].uv = (sx, 0)
bmc = bmesh.new(); bme = bmesh.new(); bme.loops.layers.uv.new('UVMap')
for ln, (w0, w1) in zip(LINES, WID):
    ribbon(ln, w0, w1, bmc, bme, None, 0.0 if ln[0] is ORIGIN else (LINES[0][1] - ORIGIN).length * 0 + 0.3)
bmesh.ops.recalc_face_normals(bmc, faces=bmc.faces[:])
bme.normal_update()
for f in bme.faces:
    if f.normal.y > 0: f.normal_flip()
bmesh.ops.triangulate(bme, faces=bme.faces[:])
mc = bpy.data.meshes.new('crackcut'); bmc.to_mesh(mc); bmc.free(); cutc = bpy.data.objects.new('crackcut', mc); sc.collection.objects.link(cutc); cutc.location = (0, 0, CZ)
for ln in LINES: pass
bpy.data.objects.remove(cutc, do_unlink=True)
# 裂口两侧的唇：一侧高 12 毫米、一侧高 4 毫米（略错位），内壁被红光照亮
bl_ = bmesh.new()
for q in CUTQ:
    n_ = (q[0] - q[3]).normalized(); lw = 0.012
    for side, hh in ((0, 0.012), (1, 0.004)):
        if side == 0: P0, P1 = q[0], q[1]; ex = n_ * lw
        else: P0, P1 = q[3], q[2]; ex = -n_ * lw
        ff = bl_.faces.new([bl_.verts.new((c.x, FACE_Y + 0.001, c.y)) for c in (P0, P1, P1 + ex, P0 + ex)])
        ee = bmesh.ops.extrude_face_region(bl_, geom=[ff]); bmesh.ops.translate(bl_, vec=(0, -hh, 0), verts=[v for v in ee['geom'] if isinstance(v, bmesh.types.BMVert)])
bmesh.ops.remove_doubles(bl_, verts=bl_.verts[:], dist=1e-5); bmesh.ops.recalc_face_normals(bl_, faces=bl_.faces[:])
ml_ = bpy.data.meshes.new('lips'); bl_.to_mesh(ml_); bl_.free(); lips_o = bpy.data.objects.new('lips', ml_); sc.collection.objects.link(lips_o); lips_o.location = (0, 0, CZ); child(lips_o)
me_e = bpy.data.meshes.new('crackem'); bme.to_mesh(me_e); bme.free()
crack_em = bpy.data.objects.new('crackem', me_e); tryset(crack_em, 'visible_volume_scatter', False); sc.collection.objects.link(crack_em); crack_em.location = (0, 0, CZ); child(crack_em)
mcr = new_mat('crack'); nc = mcr.node_tree
for n in list(nc.nodes):
    if n.type != 'OUTPUT_MATERIAL': nc.nodes.remove(n)
emc = nc.nodes.new('ShaderNodeEmission'); emc.inputs['Color'].default_value = (*RED, 1)
uvn = nc.nodes.new('ShaderNodeTexCoord'); sep = nc.nodes.new('ShaderNodeSeparateXYZ'); lt = nc.nodes.new('ShaderNodeMath'); lt.operation = 'LESS_THAN'
nc.links.new(uvn.outputs['UV'], sep.inputs['Vector']); nc.links.new(sep.outputs['X'], lt.inputs[0])
mulc = nc.nodes.new('ShaderNodeMath'); mulc.operation = 'MULTIPLY'; nc.links.new(lt.outputs[0], mulc.inputs[0]); mulc.inputs[1].default_value = 0.0
nc.links.new(mulc.outputs[0], emc.inputs['Strength']); with_fade(mcr, emc.outputs[0]); me_e.materials.append(mcr)
CRACK_GROW = lt.inputs[1]; CRACK_STR = mulc.inputs[1]; CRACK_FADE = FADEKEYS[-1]
ml_.materials.append(cmat)   # 唇与牌共用材质（共用 fade）

# 3) 碎屑：8 片小黑曜石屑，裂开时飞起
SHARDS = []
m_sh = obsidian('shard')
for k in range(8):
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=random.uniform(0.02, 0.05), depth=random.uniform(0.03, 0.07))
    o = bpy.context.object; o.data.materials.append(m_sh); child(o)
    p0 = Vector((0.6 + random.uniform(-0.3, 0.3), FACE_Y - 0.02, random.uniform(-0.3, 0.35)))
    v = Vector((random.uniform(-0.2, 0.55), random.uniform(-0.9, -0.3), random.uniform(-0.15, 0.4)))
    SHARDS.append((o, p0, v, Vector((random.uniform(-6, 6), random.uniform(-6, 6), random.uniform(-6, 6)))))

# 4) 字槽里的发光层（槽底）：比槽口小一点，露出槽壁；颜色 琥珀→冷白
glyph = []
for ch, gx in zip('做完了', GX):
    m, em = emit_mat('g_' + ch, AMBER, 3.0)
    o = mktext(ch, GSIZE * 0.975, gx, CZ, FACE_Y + 0.03 - 0.004, m, font_black, extrude=0.002, name='inlay_' + ch)
    glyph.append((o, m, em))
for _o, _m, _e in glyph: tryset(_o, 'visible_volume_scatter', False)
# 牌面蚀刻小字“示意”（重排到看得清）
m_et, em_et = emit_mat('etch', COLD, 1.4)
mktext('示意 · 任务#3', 0.085, -0.62, CZ - 0.47, FACE_Y - 0.003, m_et, font_reg, extrude=0.002, bevel=0.0008, name='etch')

# ---------- 扫光：灯在画外，前面一道缝，光带在牌面和字槽上滑过，雾里有一束光锥 ----------
def hide_from_rays(o):
    for k in ('visible_camera', 'visible_glossy', 'visible_diffuse', 'visible_transmission'): tryset(o, k, False)
LPOS = Vector((-3.4, -3.6, 2.5))
sl = bpy.data.lights.new('slit', 'POINT'); sl.shadow_soft_size = 0.008; sl.color = (0.78, 0.9, 1.0); sl.energy = 0
slit = bpy.data.objects.new('slit', sl); sc.collection.objects.link(slit); slit.location = LPOS
pivot = bpy.data.objects.new('pivot', None); sc.collection.objects.link(pivot)
mblk = bpy.data.materials.new('blk'); use_nodes(mblk)
GAP = 0.04
for sgn in (-1, 1):
    bpy.ops.mesh.primitive_cube_add(size=1); bo = bpy.context.object; bo.scale = (30, 30, 0.02); bo.location = (sgn * (15 + GAP / 2), 0, 0); bo.parent = pivot
    bo.data.materials.append(mblk); hide_from_rays(bo)
# 一盏窄条主光：从牌的一端亮到另一端，用来出边缘高光（粗细不匀靠崩口）
def mkarea(name, loc, tgt, sx, sy, energy, color, roll=0.0):
    l = bpy.data.lights.new(name, 'AREA'); l.shape = 'RECTANGLE'; l.size = sx; l.size_y = sy; l.energy = energy; l.color = color
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o); o.location = loc
    q = (Vector(tgt) - o.location).to_track_quat('-Z', 'Y') @ Quaternion((0, 0, 1), roll); o.rotation_euler = q.to_euler()
    tryset(o, 'visible_volume_scatter', False); return o
mkarea('keystrip', (-3.4, -1.0, 1.6), (0, 0, CZ), 0.10, 2.4, 380, (0.92, 0.96, 1.0), math.radians(28))
mkarea('topstrip', (-0.8, -1.8, 2.6), (0, 0, CZ + 0.3), 3.2, 0.08, 1500, (0.9, 0.95, 1.0), math.radians(9))
mkarea('rim', (3.0, 1.8, 1.0), (0, 0, CZ), 0.3, 1.4, 500, (0.46, 0.62, 1.0))

# ---------- 地面：湿黑抛光，镜像随离牌距离衰减、略糊；暖光是柔光晕，没有椭圆边 ----------
bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0)); floor = bpy.context.object
fm = new_mat('floor'); fn = fm.node_tree; fb = fn.nodes['Principled BSDF']
tcf = fn.nodes.new('ShaderNodeTexCoord'); sp_ = fn.nodes.new('ShaderNodeSeparateXYZ'); ab = fn.nodes.new('ShaderNodeMath'); ab.operation = 'ABSOLUTE'
vl = fn.nodes.new('ShaderNodeVectorMath'); vl.operation = 'LENGTH'
fn.links.new(tcf.outputs['Object'], sp_.inputs['Vector']); fn.links.new(sp_.outputs['Y'], ab.inputs[0]); fn.links.new(tcf.outputs['Object'], vl.inputs[0])
def maprange(a0, b0, c0, d0, src):
    n = fn.nodes.new('ShaderNodeMapRange'); n.inputs['From Min'].default_value = a0; n.inputs['From Max'].default_value = b0
    n.inputs['To Min'].default_value = c0; n.inputs['To Max'].default_value = d0; n.clamp = True
    fn.links.new(src, n.inputs['Value']); return n
fn.links.new(maprange(0.0, 3.0, 0.03, 0.32, ab.outputs[0]).outputs['Result'], fb.inputs['Roughness'])
fn.links.new(maprange(0.0, 2.6, 1.0, 0.0, ab.outputs[0]).outputs['Result'], fb.inputs['Specular IOR Level'])
fb.inputs['Base Color'].default_value = (0.003, 0.004, 0.007, 1)
r2 = fn.nodes.new('ShaderNodeMath'); r2.operation = 'MULTIPLY'; fn.links.new(vl.outputs['Value'], r2.inputs[0]); fn.links.new(vl.outputs['Value'], r2.inputs[1])
ng = fn.nodes.new('ShaderNodeMath'); ng.operation = 'MULTIPLY'; ng.inputs[1].default_value = -2.2; fn.links.new(r2.outputs[0], ng.inputs[0])
ex = fn.nodes.new('ShaderNodeMath'); ex.operation = 'POWER'; ex.inputs[0].default_value = 2.71828; fn.links.new(ng.outputs[0], ex.inputs[1])
mu = fn.nodes.new('ShaderNodeMath'); mu.operation = 'MULTIPLY'; mu.inputs[1].default_value = 0.10; fn.links.new(ex.outputs[0], mu.inputs[0])
fb.inputs['Emission Color'].default_value = (*AMBER, 1); fn.links.new(mu.outputs[0], fb.inputs['Emission Strength'])
floor.data.materials.append(fm)

# 尘点：15 颗，很小，只在光锥里亮
random.seed(7); m_du = new_mat('dust'); bd = m_du.node_tree.nodes['Principled BSDF']; bd.inputs['Base Color'].default_value = (1, 1, 1, 1)
if 'Emission Color' in bd.inputs: bd.inputs['Emission Color'].default_value = (0.8, 0.9, 1, 1); bd.inputs['Emission Strength'].default_value = 0.12
for k in range(15):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.004, segments=8, ring_count=6, location=(random.uniform(-1.8, 1.8), random.uniform(-1.6, 1.2), random.uniform(0.1, 1.5)))
    bpy.context.object.data.materials.append(m_du); tryset(bpy.context.object, 'visible_volume_scatter', False)

# 摄像机：低、近、转角度；浅景深
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.camera = cam; sc.collection.objects.link(cam)
cd = cam.data; cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 24; cd.lens = 12 / math.tan(math.radians(16)); cd.dof.use_dof = True; cd.dof.aperture_fstop = 2.0
CAM_Z = 0.26; AIM_Z = 0.70

def card_world(xc, yc, zc):
    return Matrix.Rotation(YAW, 3, 'Z') @ Vector((xc, yc, 0)) + Vector((0, 0, zc))

def setframe(i):
    t = i / FPS
    kf = lambda owner, path: owner.keyframe_insert(path, frame=i)
    ks = lambda sock: sock.keyframe_insert('default_value', frame=i)
    u = seg(t, 3.3, 4.6); v = seg(t, 5.0, 6.6)
    if t < 5.0: y = BACK * p3in(u); fade = u ** 1.5
    else:
        e = expo_out(v); y = BACK * (1 - e); fade = 1 - cl(e * 1.15)
    G.location = (0, y, 0); kf(G, 'location')
    for s in FADEKEYS: s.default_value = fade; ks(s)
    cracked = HIT <= t < 4.6
    ls_ = 1.0 if cracked else 0.0001; lips_o.scale = (ls_, ls_, ls_); kf(lips_o, 'scale'); crack_em.scale = (ls_, ls_, ls_); kf(crack_em, 'scale')
    # 字光：琥珀；裂纹时 35%，退回 15%；第二遍扫光过处变冷白
    dim = 1.0
    if t >= HIT: dim = 1 - 0.65 * seg(t, HIT, HIT + 0.1)
    if 3.3 <= t < 5.0: dim = 0.35 - 0.20 * u
    if t >= 5.0: dim = 0.15 + 0.85 * seg(t, 5.0, 5.6)
    for (o, m, em), gx in zip(glyph, GX):
        cw = sstep(seg(t, pass_t(gx, S2, D2), pass_t(gx, S2, D2) + 0.12)) if t >= S2 else 0.0
        col = tuple(AMBER[k] * (1 - cw) + COLD[k] * cw for k in range(3))
        em.inputs['Color'].default_value = (*col, 1); em.inputs['Strength'].default_value = (3.0 + 1.8 * cw) * (dim if cw == 0 else max(dim, 1.0 if t > 5.6 else 0.0))
        ks(em.inputs['Color']); ks(em.inputs['Strength'])
    # 裂纹：红光从缝里透出来，长出来 3 帧
    cg = expo_out(seg(t, HIT, HIT + 0.1)); cs = 1.3 * (1 - sstep(seg(t, 4.2, 4.4))) if t >= HIT else 0.0
    CRACK_GROW.default_value = 3.0 * cg; ks(CRACK_GROW); CRACK_STR.default_value = cs; ks(CRACK_STR)
    for (o, p0, vv, spin) in SHARDS:
        dt = t - HIT
        if dt >= 0 and cracked:
            o.location = p0 + vv * dt * (1 - 0.35 * dt); o.rotation_euler = (spin.x * dt, spin.y * dt, spin.z * dt); o.scale = (1, 1, 1)
        else: o.scale = (0.0001,) * 3
        kf(o, 'location'); kf(o, 'rotation_euler'); kf(o, 'scale')
    # 扫光：缝的位置跟着扫光走
    if t < S2 - 0.2:
        bx = BAR_X0 - 0.3 * (1 - p2out(seg(t, 1.0, 1.3))) if t < S1 else sweep_x(t, S1, D1)
        bon = cl((t - 1.0) / 0.25) * (1 - seg(t, 3.25, 3.5))
    else:
        bx = sweep_x(t, S2, D2); bon = cl((t - (S2 - 0.15)) / 0.15) * (1 - seg(t, S2 + D2, S2 + D2 + 0.25))
    H = card_world(bx, FACE_Y, CZ) + Vector((0, y, 0))
    pivot.location = LPOS + (H - LPOS) * 0.55
    pivot.rotation_euler = (H - LPOS).to_track_quat('Z', 'Y').to_euler(); kf(pivot, 'location'); kf(pivot, 'rotation_euler')
    sl.energy = 36000.0 * bon * (0 if os.environ.get('NOSLIT') else 1); sl.keyframe_insert('energy', frame=i)
    # 摄像机：缓推；撞击抖一下；第二遍扫光时推进
    dist = 3.15 - 0.2 * cl(t / 5.0)
    if t >= 5.0: dist = 2.95
    if t >= S2: dist = 2.95 - 0.10 * p2io(seg(t, S2, S2 + 1.0))
    if t >= HIT: dist += 0.05 * math.exp(-(t - HIT) * 12) * math.sin((t - HIT) * 60 + 1.2)
    camx = 0.25 * (1 - cl(t / 6.6)) - 0.1
    cam.location = (camx, -dist, CAM_Z); tg = Vector((0.0, 0, AIM_Z))
    cam.rotation_euler = (tg - cam.location).to_track_quat('-Z', 'Y').to_euler(); cd.dof.focus_distance = (Vector((0, 0, CZ)) - cam.location).length
    kf(cam, 'location'); kf(cam, 'rotation_euler'); cd.dof.keyframe_insert('focus_distance', frame=i)

for i in range(NF): setframe(i)
if os.environ.get('BORDER'):
    bx0, bx1, by0, by1 = [float(q) for q in os.environ['BORDER'].split(',')]
    r.use_border = True; r.border_min_x = bx0; r.border_max_x = bx1; r.border_min_y = by0; r.border_max_y = by1; r.use_crop_to_border = True
res = []
os.makedirs(out, exist_ok=True)
print('S1', round(S1, 3), 'HIT', HIT, 'pass_t(1)', [round(pass_t(g, S1, D1), 3) for g in GX], 'pass_t(2)', [round(pass_t(g, S2, D2), 3) for g in GX])
for i in fl:
    sc.frame_set(i)
    r.filepath = os.path.join(out, f'f{i:04d}.png'); a0 = time.time(); bpy.ops.render.render(write_still=True); res.append((i, round(time.time() - a0, 1)))
print('RESULT per-frame sec', res, 'blender', bpy.app.version_string)
