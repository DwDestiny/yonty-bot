/**
 * Input:  飞书网页版里跟机器人的私聊页面。私聊里要有机器人发的富文本回复（带引用）和自己发的消息，脚本拿它们当消息样式。
 *         scenes.json 里 scenes 下的一段，传给 ybCompose(scene)、ybCheck(scene, clip)。
 * Output: ybCompose 把原消息列表藏起来，换成拼好的静态列表，改群名和群头像，返回截取范围 clip（CSS 像素）。
 *         ybCheck 列出截取范围里看得见、却不在这段台词里的字和图，三个列表都空才能截。
 * Pos:    docs/assets/scenes/ 两张群聊场景图的拼图脚本，在开发者工具里运行。只改本机网页，不发消息；飞书改版后类名可能对不上。
 */
(() => {
  const NAMES = { bot: '小助理', owner: '周宇', chen: '老陈', lin: '小林', su: '小苏' };
  const av = (txt, bg, fg, fs) => 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><circle cx="40" cy="40" r="40" fill="' + bg + '"/>' +
    '<text x="40" y="40" dy="0.36em" text-anchor="middle" font-family="PingFang SC, Helvetica, Arial, sans-serif" font-size="' + fs +
    '" font-weight="600" fill="' + fg + '">' + txt + '</text></svg>');
  const AV = { bot: av('Y', '#1c1a17', '#f4efe6', 40), owner: av('周宇', '#4e83fd', '#ffffff', 26), chen: av('老陈', '#ff8800', '#ffffff', 26),
               lin: av('小林', '#7f3bf5', '#ffffff', 26), su: av('小苏', '#00a3a3', '#ffffff', 26), group: av('shop', '#3370ff', '#ffffff', 24) };
  const MENTION = /(@(?:小助理|周宇|老陈|小林|小苏))/;
  const IS_MENTION = /^@(?:小助理|周宇|老陈|小林|小苏)$/;
  const URL = /(https?:\/\/[^\s，。]+)/;
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const GAP = '<div style="margin-bottom: var(--md-box-paragraph-spacing);"></div>';   // 飞书富文本段落之间的空行
  // 水印层、光标、长消息的“展开”遮罩都不要
  const CSS = "div[style*='position: fixed'][style*='pointer-events: none'][style*='background-image: url(\"data:image']{display:none!important}" +
    " *{caret-color:transparent!important} .yb-overlay .height-limit-cut-modal{display:none!important}" +
    " .yb-overlay .limit-height-container{max-height:none!important;height:auto!important;overflow:visible!important}";

  const templates = rows => {
    if (window.__ybTemplates) return window.__ybTemplates;
    const first = r => r.querySelector('.message-item-first'), self = r => r.querySelector('.message-self');
    const bot = rows.find(r => first(r) && !self(r) && r.querySelector('.flow-markdown-body') && r.querySelector('.reply-header'));
    const mine = rows.find(r => first(r) && self(r) && r.querySelector('.message-text'));
    if (!bot || !mine) throw new Error('私聊里找不到机器人的富文本回复或自己发的消息，换一个有这两种消息的私聊');
    const code = document.querySelector('.flow-markdown-body code');
    window.__ybTemplates = { bot: bot.cloneNode(true), self: mine.cloneNode(true), codeClass: code ? code.className : '',
                             paraClass: (bot.querySelector('.paragraph-element') || {}).className || 'paragraph-element' };
    return window.__ybTemplates;
  };

  window.ybCompose = async (scene) => {
    let st = document.getElementById('yb-style');
    if (!st) { st = document.createElement('style'); st.id = 'yb-style'; document.head.appendChild(st); }
    st.textContent = CSS;
    const rows = [...document.querySelectorAll('.messageList-row-wrapper')].filter(r => !r.closest('.yb-overlay'));
    const T = templates(rows);
    const plain = s => s.split(MENTION).map(p => !p ? '' : IS_MENTION.test(p)
      ? '<span class="text-only" style="color:rgb(20,86,240)">' + esc(p) + '</span>' : '<span class="text-only">' + esc(p) + '</span>').join('');
    const rich = s => s.split(URL).map(seg => URL.test(seg)
      ? '<a class="link rich-text-anchor" style="color:rgb(20,86,240)">' + esc(seg) + '</a>'
      : seg.split(/(`[^`]+`)/).map(p => p.length > 2 && p[0] === '`' && p[p.length - 1] === '`'
          ? '<code class="' + T.codeClass + '">' + esc(p.slice(1, -1)) + '</code>' : plain(p)).join('')).join('');

    // 原列表是虚拟滚动，直接改会错位：藏起来，在旁边放一层静态列表
    const real = rows.length ? rows[0].parentElement : document.querySelector('.yb-real');
    real.classList.add('yb-real');
    document.querySelectorAll('.yb-overlay').forEach(e => e.remove());
    const ov = document.createElement('div');
    ov.className = [...real.classList].filter(c => c !== 'yb-real').join(' ') + ' yb-overlay';
    ov.style.cssText = 'position:relative;height:auto;padding:12px 0 12px';
    real.style.display = 'none';
    real.parentElement.insertBefore(ov, real.nextSibling);

    for (const m of scene.msgs) {
      const isBot = m.who === 'bot', isSelf = m.who === 'owner';
      const row = (isBot ? T.bot : T.self).cloneNode(true);
      Object.assign(row.style, { position: 'relative', transform: 'none', top: 'auto', left: 'auto' });
      const item = row.querySelector('.js-message-item');
      if (!isSelf) { item.classList.remove('message-self'); item.classList.add('message-not-self'); }
      row.querySelectorAll('.chat-message-metas').forEach(e => { e.innerHTML = ''; });   // 已读、回复数
      const quote = row.querySelector('.reply-header');
      if (quote && m.reply) {
        quote.querySelector('.referencePreviewTitle__name span').textContent = '回复 ' + m.reply.name + '：';
        quote.querySelector('.referencePreviewTitle__message .text-only').textContent = m.reply.text;
      } else if (quote) quote.remove();
      if (isBot) {
        row.querySelector('.flow-markdown-body').innerHTML = m.text.split('\n\n')
          .map(p => '<div class="' + T.paraClass + '">' + p.split('\n').map(rich).join('<br>') + '</div>').join(GAP);
      } else {
        (row.querySelector('.message-text .richTextContainer') || row.querySelector('.richTextContainer')).innerHTML = plain(m.text);
      }
      const left = row.querySelector('.message-left'), info = row.querySelector('.message-info');
      if (m.grouped) {   // 同一个人连着发：不显示头像和名字
        item.classList.remove('message-item-first');
        left.innerHTML = '<span class="message-timestamp noselect message-layout-time-tip">' + m.time + '</span>';
        if (info) info.remove();
      } else {
        const img = row.querySelector('img.ud__avatar__image');
        img.removeAttribute('srcset'); img.src = AV[m.who];
        info.innerHTML = '<span style="margin-right:8px">' + NAMES[m.who] + '</span><span class="message-timestamp noselect message-layout-time-tip">' + m.time + '</span>';
      }
      ov.appendChild(row);
    }

    // 顶栏：群名、群头像；藏起会话描述、标签和多出来的页签
    const name = document.querySelector('.chatWindow_chatName');
    name.textContent = scene.title;
    const title = name.closest('.chatWindow_header_title');
    [...title.children].forEach(c => { if (!c.contains(name)) c.style.display = 'none'; });
    document.querySelectorAll('.chatNewWindow_statusDesc, .chatWindow_header_metas').forEach(e => { e.style.display = 'none'; });
    const head = name.closest('.chatWindow_tabHeader');
    document.querySelectorAll('.chatWindow_avatar img, .chatWindow_avatar_wrapper img').forEach(i => { i.removeAttribute('srcset'); i.src = AV.group; });
    name.closest('.chatWindow_header_wrapper').querySelectorAll('img').forEach(i => { i.removeAttribute('srcset'); i.src = AV.group; });
    const tab = [...head.querySelectorAll('*')].find(e => e.children.length === 0 && (e.textContent || '').trim() === '任务仪表盘');
    if (tab) { let e = tab; while (e.parentElement && !(e.parentElement.textContent || '').includes('消息')) e = e.parentElement; e.style.display = 'none'; }

    let box = ov.parentElement;
    while (box && !/(auto|scroll)/.test(getComputedStyle(box).overflowY)) box = box.parentElement;
    if (box) box.scrollTop = 0;
    await new Promise(r => setTimeout(r, 500));
    const r = ov.getBoundingClientRect();
    return { x: Math.round(r.left), y: 6, w: Math.round(r.width), h: Math.round(r.bottom) - 6 };
  };

  window.ybCheck = (scene, clip) => {
    const allowed = [scene.title, '消息', '+'];
    for (const m of scene.msgs) {
      allowed.push(m.text.replace(/`/g, ''), m.time, NAMES[m.who]);
      if (m.reply) allowed.push('回复 ' + m.reply.name + '：', m.reply.text);
    }
    const all = allowed.join('\n');
    const seen = (el, r) => {   // 在截取范围里，而且没被别的元素盖住
      const x0 = Math.max(r.left, clip.x), x1 = Math.min(r.right, clip.x + clip.w), y0 = Math.max(r.top, clip.y), y1 = Math.min(r.bottom, clip.y + clip.h);
      if (x1 <= x0 + 0.5 || y1 <= y0 + 0.5) return false;
      const t = document.elementFromPoint((x0 + x1) / 2, (y0 + y1) / 2);
      return !!t && (t === el || el.contains(t) || t.contains(el));
    };
    const texts = [];
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const t = tw.currentNode, s = (t.textContent || '').trim();
      if (!s || !t.parentElement) continue;
      const rg = document.createRange(); rg.selectNodeContents(t);
      if ([...rg.getClientRects()].some(r => seen(t.parentElement, r)) && !all.includes(s)) texts.push(s.slice(0, 40));
    }
    const images = [...document.querySelectorAll('img')].filter(i => seen(i, i.getBoundingClientRect()) && !(i.getAttribute('src') || '').startsWith('data:image/svg+xml')).map(i => i.className);
    const backgrounds = [...document.querySelectorAll('body *')].filter(e => {
      const b = getComputedStyle(e).backgroundImage;
      return b && b !== 'none' && !/data:image|gradient/.test(b) && seen(e, e.getBoundingClientRect());
    }).map(e => String(e.className));
    return { texts, images, backgrounds };
  };
})();
