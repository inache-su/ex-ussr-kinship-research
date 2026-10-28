/* All personal data stays in this local document. No network requests. */
'use strict';
const treeData = JSON.parse(document.getElementById('tree-data').textContent);
const ui = JSON.parse(document.getElementById('tree-copy').textContent);
const $ = (id) => document.getElementById(id);
const drawnRelationships = treeData.relationships.filter((edge) => edge.status !== 'contradicted');
const people = new Map(treeData.people.map((person) => [person.id, person]));
const viewport = $('viewport');
const surface = $('surface');
const svg = $('tree');
const ns = 'http://www.w3.org/2000/svg';
const textMeasure = document.createElement('canvas').getContext('2d');
const cardW = treeData.cardWidth;
const cardH = treeData.cardHeight;
let scale = 1;
let selectedId = null;
let activeBranch = 'all';
let focusOrigin = null;
let drag = null;
let rootId = treeData.people[0]?.id;
let activeSection = 'tree';
let activeView = 'all';
let viewFocusId = rootId;
let visibleIds = new Set(people.keys());
let currentPath = null;


const SVG_STYLE = `
  .graph-section{font:500 22px Literata,Georgia,serif;fill:#4f5b57}
  .person{cursor:pointer;outline:none}.person .card{fill:#fffdf8;stroke:#b9ae98;stroke-width:1.2}
  .person:hover .card,.person:focus-visible .card{stroke:#1d5c57;stroke-width:3}
  .person.selected .card{fill:#ddeae5;stroke:#1d5c57;stroke-width:2.8}.person.related .card{stroke:#7a827d;stroke-width:1.8}
  .person.search-hit .card{stroke:#8a5a0e;stroke-width:3}.person.root .card{stroke:#7e5416;stroke-width:2}
  .card-name{font:600 16px Literata,Georgia,serif;fill:#1c2826}
  .card-life{font:13px 'Golos Text',Arial,sans-serif;fill:#4f5b57}
  .card-root-label{font:500 10px 'Golos Text',Arial,sans-serif;fill:#7e5416}
  .provisional-mark{fill:#8a5a0e}.card-version{font:11px 'Golos Text',Arial,sans-serif;fill:#8a5a0e}
  .edge{cursor:pointer;outline:none}.edge-line{fill:none;stroke:#56625e;stroke-width:1.8}
  .edge-underlay{fill:none;stroke:#efeadf;stroke-width:7}.edge-hit{fill:none;stroke:transparent;stroke-width:15}
  .edge.document .edge-line{stroke:#1d5c57}.edge.hypothesis .edge-line{stroke:#8a5a0e;stroke-dasharray:8 5}
  .edge.spiritual .edge-line,.edge.godparent .edge-line{stroke:#6a4e79;stroke-dasharray:2 5}.edge.unplaced .edge-line{stroke:#4f5b57;stroke-dasharray:2 6}
  .edge.step .edge-line{stroke-dasharray:5 5}.edge.active .edge-line,.edge:focus-visible .edge-line,.edge:hover .edge-line{stroke-width:3.5}
  .edge-label{font:11px 'Golos Text',Arial,sans-serif;fill:#4f5b57;paint-order:stroke;stroke:#efeadf;stroke-width:6px;stroke-linejoin:round;pointer-events:none}
  .edge.unplaced .edge-label{fill:#4f5b57}.edge.spiritual .edge-label{fill:#6a4e79}
  .view-hidden,.is-filtered{display:none}
`;
$('svg-styles').textContent = SVG_STYLE;

function element(tag, attributes = {}, text = null) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== null) node.textContent = text;
  return node;
}

function htmlElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fullName(person) {
  if (!person) return '';
  return [person.surname, person.name, person.patronymic].filter(Boolean).join(' ');
}

function countLabel(count, forms) {
  const last = count % 10, lastTwo = count % 100;
  return `${count} ${forms[last === 1 && lastTwo !== 11 ? 0 : last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14) ? 1 : 2]}`;
}

function normalize(value) {
  return value.normalize('NFKC').toLocaleLowerCase('ru').replaceAll('ё', 'е');
}

function wrap(value, limit = treeData.cardWidth - 32, font = '600 16px Literata, Georgia, serif') {
  textMeasure.font = font;
  const lines = [''];
  for (const word of value.split(/\s+/)) {
    const chunks = [''];
    for (const char of word) {
      const last = chunks.length - 1;
      if (chunks[last] && textMeasure.measureText(chunks[last] + char).width > limit) chunks.push(char);
      else chunks[last] += char;
    }
    for (const chunk of chunks) {
      const last = lines.length - 1;
      const candidate = lines[last] ? lines[last] + ' ' + chunk : chunk;
      if (lines[last] && textMeasure.measureText(candidate).width > limit) lines.push(chunk);
      else lines[last] = candidate;
    }
  }
  return lines;
}

function generationDepth(id, seen = new Set()) {
  if (seen.has(id)) return 0;
  const parents = drawnRelationships.filter((edge) => edge.kind === 'parent' && edge.to === id);
  return 1 + Math.max(0, ...parents.map((edge) => generationDepth(edge.from, new Set([...seen, id]))));
}

function initializeCopy() {
  ui.dataDate = ui.dataDate.replace('{date}', new Date(`${treeData.updated}T00:00:00`).toLocaleDateString('ru-RU', {day:'numeric',month:'long',year:'numeric'}));
  document.querySelectorAll('[data-copy]').forEach((node) => { node.textContent = ui[node.dataset.copy]; });
  document.querySelectorAll('[data-label]').forEach((node) => { node.setAttribute('aria-label', ui[node.dataset.label]); });
  document.querySelectorAll('[data-placeholder]').forEach((node) => { node.placeholder = ui[node.dataset.placeholder]; });
  $('data-date').textContent = ui.dataDate;
  $('summary').textContent = `${countLabel(people.size, ui.peopleForms)}, ${countLabel(Math.max(0, ...treeData.people.map((person) => generationDepth(person.id))), ui.generationForms)}`;
  $('root-name').textContent = fullName(people.get(rootId));
  for (const [id, label] of Object.entries(treeData.branches)) {
    const option = htmlElement('option', null, label); option.value = id; $('branch').append(option);
  }
  if (!people.size) document.querySelectorAll('[data-view],#root-person,#center-me,#mobile-view').forEach((node) => { node.disabled = true; });
  for (const person of [...people.values()].sort((a,b)=>fullName(a).localeCompare(fullName(b),'ru'))) {
    for (const id of ['path-from','path-to']) { const option=htmlElement('option',null,fullName(person)); option.value=person.id; $(id).append(option); }
  }
}

function edgePath(edge) {
  const a = people.get(edge.from), b = people.get(edge.to);
  const ax = a.x + cardW / 2, bx = b.x + cardW / 2;
  const ay = a.y + cardH, by = b.y;
  if (edge.kind === 'parent') {
    const union = treeData.unions.find((item) => item.parents.includes(a.id) && item.children.includes(b.id));
    const rail = union.rail + union.parents.indexOf(a.id) * 13;
    return `M${ax},${ay} V${rail} H${bx} V${by}`;
  }
  if (edge.kind === 'spouse' || edge.kind === 'partner') {
    if (Math.abs(a.x - b.x) < 400) {
      const left = a.x < b.x ? a : b, right = a.x < b.x ? b : a;
      return `M${left.x + cardW},${left.y + cardH / 2} H${right.x}`;
    }
    const rail = Math.max(a.y, b.y) + cardH + 26;
    return `M${ax},${ay} V${rail} H${bx} V${b.y + cardH}`;
  }
  const rail = edge.rail ?? Math.max(ay, b.y + cardH) + 36;
  return `M${ax},${ay} V${rail} H${bx} V${b.y + cardH}`;
}

function renderGraph() {
  svg.setAttribute('viewBox', `0 0 ${treeData.width} ${treeData.height}`);
  svg.querySelector(':scope > rect')?.remove();
  svg.insertBefore(element('rect', {x:0,y:0,width:treeData.width,height:treeData.height,fill:'#efeadf'}),$('sections'));
  for (const id of ['sections','edges','nodes']) $(id).replaceChildren();
  for (const section of treeData.sections) $('sections').append(element('text', {x:section.x,y:section.y,class:'graph-section'},section.text));
  for (const edge of drawnRelationships) {
    const title=`${ui.relationNames[edge.kind]}: ${fullName(people.get(edge.from))}, ${fullName(people.get(edge.to))}. ${ui[edge.status]}`;
    const group=element('g',{class:`edge ${edge.status} ${edge.kind}`,'data-edge':edge.id,role:'button',tabindex:'0','aria-label':title});
    group.append(element('title',{},title+(edge.note?'. '+edge.note:'')));
    for (const className of ['edge-underlay','edge-line','edge-hit']) group.append(element('path',{d:edgePath(edge),class:className}));
    if (edge.kind==='sibling') group.append(element('text',{x:edge.labelX,y:edge.rail-12,'text-anchor':'middle',class:'edge-label'},ui.siblingLine));
    if (edge.kind==='unplaced') group.append(element('text',{x:edge.labelX,y:edge.rail-11,'text-anchor':'middle',class:'edge-label'},edge.label??ui.unplacedLine));
    if (edge.kind==='step') group.append(element('text',{x:edge.labelX,y:edge.rail-12,'text-anchor':'middle',class:'edge-label'},ui.stepLine));
    group.addEventListener('click',()=>showRelationship(edge));
    group.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showRelationship(edge);}});
    $('edges').append(group);
  }
  for (const person of treeData.people) {
    const isRoot=person.id===rootId;
    const group=element('g',{class:'person'+(isRoot?' root':''),'data-id':person.id,'data-family':person.family,transform:`translate(${person.x} ${person.y})`,role:'button',tabindex:'0','aria-label':`${fullName(person)}. ${person.role}. ${person.life}`});
    group.append(element('title',{},fullName(person)+'. '+person.role));
    group.append(element('rect',{width:cardW,height:cardH,rx:6,class:'card'}));
    if(isRoot){group.append(element('rect',{x:12,y:9,width:115,height:17,rx:3,fill:'#f1e4cc'}));group.append(element('text',{x:18,y:21,class:'card-root-label'},ui.rootShort));}
    const name=[person.name,person.patronymic,person.surname].filter(Boolean).join(' ');
    const lines=wrap(name);
    lines.slice(0,3).forEach((line,index)=>group.append(element('text',{x:14,y:(isRoot?46:28)+index*21,class:'card-name'},line)));
    const lifeY=Math.max(isRoot?94:83,(isRoot?46:28)+Math.min(lines.length,3)*21+6);
    wrap(person.life,cardW-32,"13px 'Golos Text', Arial, sans-serif").slice(0,2).forEach((line,index)=>group.append(element('text',{x:14,y:Math.min(lifeY,cardH-24)+index*16,class:'card-life'},line)));
    if(person.provisional)group.append(element('path',{d:`M${cardW-20} 11 l7 13 h-14 Z`,class:'provisional-mark'}));
    group.addEventListener('click',()=>showPerson(person.id));
    group.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showPerson(person.id);}});
    $('nodes').append(group);
  }
}

function renderPeople(query = $('search').value) {
  const list=treeData.people.filter((person)=>matchesPerson(person,query)).sort((a,b)=>fullName(a).localeCompare(fullName(b),'ru'));
  $('people-list').replaceChildren();
  $('list-count').textContent=query.trim()?`${list.length} / ${people.size}`:people.size;
  document.querySelectorAll('.person').forEach((node)=>node.classList.toggle('search-hit',!!query.trim()&&list.some((p)=>p.id===node.dataset.id)));
  for(const person of list){
    const row=htmlElement('button','person-row');row.type='button';row.dataset.person=person.id;row.setAttribute('aria-current',String(selectedId===person.id));
    const label=htmlElement('span');label.append(htmlElement('strong',null,fullName(person)),htmlElement('small',null,person.life));
    const arrow=htmlElement('span','row-arrow','›');arrow.setAttribute('aria-hidden','true');row.append(label,arrow);
    row.addEventListener('click',()=>showPerson(person.id));$('people-list').append(row);
  }
  if(!list.length)$('people-list').append(htmlElement('p','empty-results',ui.noResults));
}

function setScale(value, anchorX = viewport.clientWidth / 2, anchorY = viewport.clientHeight / 2) {
  const newScale = Math.min(1.8, Math.max(.1, value));
  const previousOffset = surfaceOffset();
  const x = (viewport.scrollLeft + anchorX - previousOffset.x) / scale, y = (viewport.scrollTop + anchorY - previousOffset.y) / scale;
  scale = newScale;
  surface.style.width = treeData.width * scale + 'px'; surface.style.height = treeData.height * scale + 'px';
  svg.setAttribute('width', treeData.width * scale); svg.setAttribute('height', treeData.height * scale);
  const offset = surfaceOffset();
  viewport.scrollLeft = x * scale + offset.x - anchorX; viewport.scrollTop = y * scale + offset.y - anchorY;
  $('zoom-value').textContent = Math.round(scale * 100) + '%';
}

function surfaceOffset() {
  return {x:Math.max(0,viewport.clientWidth-treeData.width*scale)/2,y:Math.max(0,viewport.clientHeight-treeData.height*scale)/2};
}

function fitPeople(items) {
  if(!items.length){$('map-status').textContent=ui.emptyView;return;}
  const minX=Math.min(...items.map((p)=>p.x))-45,minY=Math.min(...items.map((p)=>p.y))-65;
  const maxX=Math.max(...items.map((p)=>p.x+cardW))+45,maxY=Math.max(...items.map((p)=>p.y+cardH))+65;
  const nextScale=Math.min((viewport.clientWidth-24)/(maxX-minX),(viewport.clientHeight-90)/(maxY-minY),1);
  setScale(nextScale,0,0);
  const offset=surfaceOffset();
  viewport.scrollLeft=Math.max(0,minX*scale+offset.x-(viewport.clientWidth-(maxX-minX)*scale)/2);
  viewport.scrollTop=Math.max(0,minY*scale+offset.y-(viewport.clientHeight-(maxY-minY)*scale)/2);
}

function centerPerson(person) {
  if(!person||viewport.hidden)return;
  setScale(Math.max(scale,.9));
  const offset=surfaceOffset();
  viewport.scrollLeft=(person.x+cardW/2)*scale+offset.x-viewport.clientWidth/2;
  viewport.scrollTop=(person.y+cardH/2)*scale+offset.y-viewport.clientHeight/2;
}

function highlight(id) {
  const relatives = new Set(drawnRelationships.filter((e) => e.from === id || e.to === id).flatMap((e) => [e.from,e.to]));
  document.querySelectorAll('.person').forEach((node) => { node.classList.toggle('selected',node.dataset.id === id); node.classList.toggle('related',node.dataset.id !== id && relatives.has(node.dataset.id)); });
  document.querySelectorAll('.edge').forEach((node) => { const edge=treeData.relationships.find((e) => e.id === node.dataset.edge); node.classList.toggle('active',edge.from === id || edge.to === id); });
  document.querySelectorAll('[data-person]').forEach((row) => row.setAttribute('aria-current',String(row.dataset.person === id)));
}

function appendLinkedText(container, text) {
  const pattern = /https?:\/\/[^\s<>]+/g;
  let start = 0;
  for (const match of text.matchAll(pattern)) {
    container.append(document.createTextNode(text.slice(start,match.index)));
    const raw = match[0], url = raw.replace(/[.,;]+$/,'');
    const link = htmlElement('a',null,url); link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; link.referrerPolicy='no-referrer';
    container.append(link, document.createTextNode(raw.slice(url.length))); start=match.index+raw.length;
  }
  container.append(document.createTextNode(text.slice(start)));
}

function relationshipLabel(edge, id) {
  if (edge.kind === 'parent') return edge.from === id ? ui.parentFrom : ui.parentTo;
  if (edge.kind === 'godparent') return edge.from === id ? ui.godparentFrom : ui.godparentTo;
  if (edge.kind === 'step') return edge.from === id ? ui.stepFrom : ui.stepTo;
  return ui[edge.kind === 'unplaced' ? 'unplacedRelation' : edge.kind];
}

function relativeButton(person, label, status) {
  const button=htmlElement('button','relative-button'); button.type='button';
  const mark=htmlElement('i','relation-mark '+status); mark.setAttribute('aria-hidden','true');
  const text=htmlElement('span'); text.append(htmlElement('small',null,label),document.createTextNode(fullName(person)));
  button.append(mark,text); button.addEventListener('click',()=>showPerson(person.id)); return button;
}

function openDetail() {
  $('app').classList.add('has-detail');
  $('detail-panel').hidden=false;
  $('back').disabled=false;
  const title=$('detail-title');title.tabIndex=-1;title.focus({preventScroll:true});
}

function showPerson(id) {
  if (!people.has(id)) return;
  focusOrigin=document.activeElement;selectedId=id;
  setSection('tree');togglePeople(false);$('map-caption').hidden=true;
  if(!visibleIds.has(id)){activeView='all';activeBranch='all';$('branch').value='all';applyView();}
  const person=people.get(id),content=$('detail-content');content.replaceChildren();
  $('panel-kicker').textContent=ui.personCard;
  const title=htmlElement('h2',null,fullName(person));title.id='detail-title';content.append(title,htmlElement('div','detail-life',person.life),htmlElement('div','detail-role',person.role));
  if(person.provisional)content.append(htmlElement('p','detail-notice',ui.provisionalNotice));
  const actions=htmlElement('div','profile-actions');
  const full=htmlElement('button','primary-button',ui.fullProfile);full.addEventListener('click',()=>{const expanded=!$('app').classList.contains('profile-expanded');$('app').classList.toggle('profile-expanded',expanded);viewport.hidden=expanded;full.textContent=expanded?ui.onTree:ui.fullProfile;if(!expanded)requestAnimationFrame(()=>centerPerson(person));});
  const root=htmlElement('button','secondary-button',ui.makeRoot);root.addEventListener('click',()=>{rootId=id;viewFocusId=id;$('root-name').textContent=fullName(person);renderGraph();applyView();highlight(id);renderPeople();$('map-status').textContent=ui.rootChanged;});
  actions.append(full,root);content.append(actions);
  const tabs=htmlElement('nav','profile-tabs');tabs.setAttribute('aria-label',ui.profileSections);content.append(tabs);
  const blocks=[];
  for(const [key,label] of [['overview',ui.profileOverview],['events',ui.events],['family',ui.relations],['sources',ui.sources]]){
    const button=htmlElement('button',null,label);button.setAttribute('aria-pressed',String(key==='overview'));
    const block=htmlElement('section','profile-block');block.dataset.profileSection=key;block.hidden=key!=='overview';blocks.push(block);
    button.addEventListener('click',()=>{tabs.querySelectorAll('button').forEach((b)=>b.setAttribute('aria-pressed',String(b===button)));blocks.forEach((b)=>b.hidden=b!==block);});tabs.append(button);content.append(block);
  }
  const [overview,events,family,sourcesBlock]=blocks;
  const info=htmlElement('dl');
  for(const [key,value] of [['birthSurname',person.birth_surname],['aliases',(person.aliases||[]).join(', ')],['oldStyleBirth',person.birth_old_style]])if(value)info.append(htmlElement('dt',null,ui[key]),htmlElement('dd',null,value));
  overview.append(info);
  for(const paragraph of person.bio.split('\n\n')){const para=htmlElement('p');appendLinkedText(para,paragraph);overview.append(para);}
  for(const event of personEvents(person))events.append(eventRow(event,false));
  if(!events.children.length)events.append(htmlElement('p',null,ui.unknownDates));
  for(const edge of treeData.relationships.filter((e)=>e.from===id||e.to===id)){const other=people.get(edge.from===id?edge.to:edge.from);const button=relativeButton(other,relationshipLabel(edge,id)+'; '+ui[edge.status],edge.status);family.append(button);if(edge.status==='contradicted'){const note=htmlElement('p','detail-notice',edge.note||ui.contradicted);family.append(note);}}
  const sources=htmlElement('ul','sources-list');
  for(const source of person.sources){const item=htmlElement('li');item.append(htmlElement('strong',null,source.id),document.createTextNode(source.title+(source.locator?' · '+source.locator:'')));sources.append(item);}
  sourcesBlock.append(sources,htmlElement('p','source-note',ui.descriptionsOnly));
  if(person.familio){const wrap=htmlElement('div','detail-links'),link=htmlElement('a',null,ui.familio);link.href=person.familio;link.target='_blank';link.rel='noopener noreferrer';wrap.append(link);overview.append(wrap);}
  highlight(id);openDetail();$('detail-panel').scrollTop=0;requestAnimationFrame(()=>centerPerson(person));
}

function showRelationship(edge) {
  focusOrigin=document.activeElement; setSection('tree'); $('panel-kicker').textContent=ui.relationCard;
  const content=$('detail-content'); content.replaceChildren();
  content.append(htmlElement('div','detail-surname',ui[edge.status]));
  const title=htmlElement('h2',null,ui.relationNames[edge.kind]);title.id='detail-title';content.append(title);
  if (edge.evidenceStatus) content.append(htmlElement('p',null,edge.id+' · '+edge.evidenceStatus));
  if (edge.note) content.append(htmlElement('p',edge.status==='hypothesis' ? 'detail-notice' : null,edge.note));
  content.append(relativeButton(people.get(edge.from),ui.relations,edge.status),relativeButton(people.get(edge.to),ui.relations,edge.status));
  if (edge.sources.length) content.append(htmlElement('p',null,ui.sources+': '+edge.sources.map((s)=>(typeof s === 'string' ? s : s.id)).join('; ')));
  openDetail(); $('detail-panel').scrollTop=0;
}

function closeDetails(restoreFocus=true) {
  $('app').classList.remove('has-detail');
  $('app').classList.remove('profile-expanded');viewport.hidden=false;$('detail-panel').hidden=true;
  $('back').disabled=activeSection==='tree';
  if(restoreFocus){const target=focusOrigin?.isConnected&&focusOrigin.getClientRects().length?focusOrigin:viewport;target.focus({preventScroll:true});}
}

function togglePeople(open) {
  $('app').classList.toggle('people-collapsed',!open);
  $('people-panel').classList.toggle('open',open&&window.innerWidth<=980);
  $('show-people').setAttribute('aria-expanded',String(open));
  $('panel-scrim').hidden=!(open&&window.innerWidth<=980);
}

function download(text,type,filename) {
  const url=URL.createObjectURL(new Blob([text],{type})),link=htmlElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000); document.querySelector('.download-menu').open=false;
}

function exportSvg() {
  const exported=svg.cloneNode(true);
  exported.setAttribute('xmlns',ns); exported.setAttribute('width',treeData.width);exported.setAttribute('height',treeData.height);
  exported.querySelectorAll('.selected,.related,.active,.search-hit,.view-hidden,.is-filtered').forEach((node)=>node.classList.remove('selected','related','active','search-hit','view-hidden','is-filtered'));
  exported.querySelectorAll('[tabindex]').forEach((node)=>node.removeAttribute('tabindex'));
  download('<?xml version="1.0" encoding="UTF-8"?>\n'+new XMLSerializer().serializeToString(exported),'image/svg+xml','family-tree.svg');
  $('map-status').textContent=ui.svgSaved;
}


function matchesPerson(person,query) {
  return normalize([fullName(person),...(person.aliases||[]),person.birth_surname||''].join(' ')).includes(normalize(query.trim()));
}

function relativesInDirection(id,direction) {
  const found=new Set([id]),queue=[id];
  for(let i=0;i<queue.length;i++)for(const edge of drawnRelationships){
    if(edge.kind!=='parent')continue;
    const from=direction==='ancestors'?edge.to:edge.from,to=direction==='ancestors'?edge.from:edge.to;
    if(from===queue[i]&&!found.has(to)){found.add(to);queue.push(to);}
  }
  return found;
}

function applyView() {
  visibleIds=new Set(people.keys());
  if(activeView==='ancestors'||activeView==='descendants')visibleIds=relativesInDirection(viewFocusId,activeView);
  if(activeView==='family')visibleIds=new Set([viewFocusId,...drawnRelationships.filter((e)=>e.from===viewFocusId||e.to===viewFocusId).flatMap((e)=>[e.from,e.to])]);
  if(activeView==='path'&&currentPath)visibleIds=new Set(currentPath.people);
  if(activeBranch!=='all')visibleIds=new Set([...visibleIds].filter((id)=>people.get(id).family===activeBranch));
  document.querySelectorAll('.person').forEach((node)=>node.classList.toggle('view-hidden',!visibleIds.has(node.dataset.id)));
  document.querySelectorAll('.edge').forEach((node)=>{const edge=treeData.relationships.find((e)=>e.id===node.dataset.edge);node.classList.toggle('view-hidden',!visibleIds.has(edge.from)||!visibleIds.has(edge.to)||(activeView==='path'&&!currentPath?.edges.includes(edge.id)));node.classList.toggle('is-filtered',!$('show-hypotheses').checked&&edge.status==='hypothesis');});
  $('sections').classList.toggle('view-hidden',activeView!=='all'||activeBranch!=='all');
  document.querySelectorAll('[data-view]').forEach((b)=>b.setAttribute('aria-pressed',String(b.dataset.view===activeView)));
  $('mobile-view').value=activeView;
  const label=ui[{all:'all',family:'familyView',ancestors:'ancestors',descendants:'descendants',path:'kinshipPath'}[activeView]];
  $('view-title').textContent=activeView==='all'?label:`${label}: ${fullName(people.get(viewFocusId))}`;
  $('map-status').textContent=visibleIds.size===people.size?countLabel(people.size,ui.peopleForms):`${ui.inView}: ${visibleIds.size} / ${people.size}`;
}

function personEvents(person) {
  return [['birth','birth_year',ui.birthEvent],['death','death_year',ui.deathEvent]].filter(([key,year])=>person[key]||person[year]).map(([key,year,title])=>({person,title,date:String(person[key]||person[year]),year:person[year]!=null&&person[year]!==''&&Number.isFinite(Number(person[year]))?Number(person[year]):Infinity}));
}

function eventRow(event,link=true) {
  const row=htmlElement('div','event-row');row.append(htmlElement('span','event-date',event.date));
  const body=htmlElement('div');body.append(htmlElement('strong',null,event.title));
  if(link){const button=htmlElement('button',null,fullName(event.person));button.addEventListener('click',()=>showPerson(event.person.id));body.append(button);}
  body.append(htmlElement('p',null,ui.fromProfile));row.append(body);return row;
}

function setSection(section) {
  if(section!=='tree')closeDetails(false);
  activeSection=section;$('app').classList.toggle('section-open',section!=='tree');
  $('app').dataset.section=section;
  $('app').classList.remove('search-open');$('mobile-search-button').setAttribute('aria-expanded','false');
  $('tree-view').hidden=section!=='tree';$('section-view').hidden=section==='tree';
  document.querySelector('.view-switch').hidden=section!=='tree';
  $('mobile-view').hidden=section!=='tree';
  document.querySelector('.filters-menu').hidden=section!=='tree';
  $('search').placeholder=section==='archive'?ui.searchArchivePlaceholder:ui.searchPlaceholder;
  $('search').setAttribute('aria-label',section==='archive'?ui.searchArchive:ui.search);
  $('search').disabled=section==='places';
  document.querySelectorAll('.main-nav [data-section]').forEach((b)=>{if(b.dataset.section===section)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('back').disabled=section==='tree'&&$('detail-panel').hidden;
  togglePeople(false);
  if(section!=='tree')renderSection();
}

function renderSection() {
  const container=$('section-content');container.replaceChildren();
  const key={people:'people',places:'places',time:'time',archive:'archive'}[activeSection];
  $('section-title').textContent=ui[key];$('section-kicker').textContent=ui.families;
  $('section-description').textContent=ui[key+'Description'];
  const query=$('search').value,list=treeData.people.filter((p)=>activeBranch==='all'||p.family===activeBranch);
  if(activeSection==='people'){
    const results=list.filter((p)=>matchesPerson(p,query)).sort((a,b)=>fullName(a).localeCompare(fullName(b),'ru'));
    const toolbar=htmlElement('div','catalogue-toolbar');toolbar.append(htmlElement('span',null,countLabel(results.length,ui.peopleForms)),htmlElement('span',null,ui.sortByName));container.append(toolbar);
    const catalogue=htmlElement('div','catalogue-list');container.append(catalogue);
    for(const person of results){const row=htmlElement('button','catalogue-row');const name=htmlElement('span','catalogue-name');name.append(htmlElement('strong',null,fullName(person)));if(person.birth_surname)name.append(htmlElement('span',null,ui.birthSurname+': '+person.birth_surname));row.append(name,htmlElement('span',null,person.life),htmlElement('span',null,treeData.branches[person.family]||person.role),htmlElement('span',null,'›'));row.addEventListener('click',()=>showPerson(person.id));catalogue.append(row);}
    if(!results.length)container.append(htmlElement('p','empty-results',ui.noResults));
  }
  if(activeSection==='archive'){
    const records=new Map();
    for(const person of list)for(const source of person.sources){const id=source.id;if(!records.has(id))records.set(id,{...source,people:new Set()});records.get(id).people.add(person.id);}
    const recordsList=[...records.values()].filter((source)=>normalize([source.id,source.title,...[...source.people].map((id)=>fullName(people.get(id)))].join(' ')).includes(normalize(query.trim())));
    for(const source of recordsList){const article=htmlElement('article','source-record');article.append(htmlElement('p',null,source.id),htmlElement('h2',null,source.title),htmlElement('p',null,ui.descriptionsOnly));const persons=htmlElement('div','source-people');for(const id of source.people){const button=htmlElement('button',null,fullName(people.get(id)));button.addEventListener('click',()=>showPerson(id));persons.append(button);}article.append(persons);container.append(article);}
    if(!recordsList.length)container.append(htmlElement('p','empty-results',ui.noSourcesFound));
  }
  if(activeSection==='time'){
    const events=list.filter((p)=>matchesPerson(p,query)).flatMap(personEvents).sort((a,b)=>a.year-b.year||a.date.localeCompare(b.date,'ru'));
    for(const event of events)container.append(eventRow(event));
    if(!events.length)container.append(htmlElement('p','empty-results',ui.noEventsFound));
  }
  if(activeSection==='places'){
    const empty=htmlElement('div','empty-section');empty.append(htmlElement('h2',null,ui.noPlaces),htmlElement('p',null,ui.noPlacesDescription));const button=htmlElement('button','primary-button',ui.openPeople);button.addEventListener('click',()=>setSection('people'));empty.append(button);container.append(empty);
  }
}

function relationshipPath(from,to,includeVersions=false) {
  const queue=[from],previous=new Map([[from,null]]);
  for(let i=0;i<queue.length&&!previous.has(to);i++)for(const edge of drawnRelationships){
    if(['godparent','unplaced','same-person'].includes(edge.kind)||(!includeVersions&&edge.status==='hypothesis'))continue;
    const other=edge.from===queue[i]?edge.to:edge.to===queue[i]?edge.from:null;
    if(other&&!previous.has(other)){previous.set(other,{person:queue[i],edge:edge.id});queue.push(other);}
  }
  if(!previous.has(to))return null;
  const ids=[to],edges=[];let cursor=to;
  while(previous.get(cursor)){const link=previous.get(cursor);edges.unshift(link.edge);ids.unshift(link.person);cursor=link.person;}
  return {people:ids,edges};
}

function showPath() {
  const from=$('path-from').value,to=$('path-to').value;
  currentPath=relationshipPath(from,to,$('path-versions').checked);
  setSection('tree');closeDetails(false);
  const content=$('detail-content');content.replaceChildren();$('panel-kicker').textContent=ui.kinshipPath;
  const title=htmlElement('h2',null,ui.kinshipPath);title.id='detail-title';content.append(title,htmlElement('p',null,currentPath?ui.pathExplanation:ui.noPath));
  if(currentPath){
    for(let i=0;i<currentPath.people.length;i++){const id=currentPath.people[i],edge=treeData.relationships.find((e)=>e.id===currentPath.edges[i-1]);content.append(relativeButton(people.get(id),edge?relationshipLabel(edge,currentPath.people[i-1])+'; '+ui[edge.status]:ui.pathFrom,edge?.status||'family'));}
    activeView='path';viewFocusId=from;activeBranch='all';$('branch').value='all';applyView();
  }
  if(!currentPath){activeView='all';applyView();}
  openDetail();if(currentPath)requestAnimationFrame(()=>fitPeople([...visibleIds].map((id)=>people.get(id))));
}

function initializeControls() {
  $('mobile-search-button').addEventListener('click',()=>{if(activeSection==='places')setSection('people');const open=!$('app').classList.contains('search-open');$('app').classList.toggle('search-open',open);$('mobile-search-button').setAttribute('aria-expanded',String(open));if(activeSection==='tree')togglePeople(open);if(open)$('search').focus();});
  $('mobile-view').addEventListener('change',()=>document.querySelector(`[data-view="${$('mobile-view').value}"]`).click());
  $('search').addEventListener('input',()=>{renderPeople();if(activeSection==='tree')togglePeople(true);else renderSection();});
  $('search').addEventListener('keydown',(event)=>{if(event.key==='Enter'&&activeSection==='tree')$('people-list').querySelector('button')?.click();});
  document.querySelectorAll('.main-nav [data-section]').forEach((button)=>button.addEventListener('click',()=>{setSection(button.dataset.section);if(activeSection==='tree')requestAnimationFrame(()=>centerPerson(people.get(selectedId||rootId)));}));
  $('branch').addEventListener('change',()=>{activeBranch=$('branch').value;applyView();if(activeSection==='tree')fitPeople([...visibleIds].map((id)=>people.get(id)));else renderSection();});
  document.querySelectorAll('[data-view]').forEach((button)=>button.addEventListener('click',()=>{if(button.dataset.view==='path'){$('path-from').value=rootId;$('path-to').value=selectedId||rootId;$('path-dialog').showModal();return;}activeView=button.dataset.view;viewFocusId=selectedId||rootId;applyView();fitPeople([...visibleIds].map((id)=>people.get(id)));}));
  $('show-hypotheses').addEventListener('change',applyView);
  $('zoom-in').addEventListener('click',()=>setScale(scale*1.25));$('zoom-out').addEventListener('click',()=>setScale(scale/1.25));
  $('fit').addEventListener('click',()=>fitPeople([...visibleIds].map((id)=>people.get(id))));
  for(const id of ['center-me','root-person'])$(id).addEventListener('click',()=>showPerson(rootId));
  $('detail-close').addEventListener('click',()=>closeDetails());
  $('show-people').addEventListener('click',()=>{togglePeople(true);$('search').focus();});
  $('close-people').addEventListener('click',()=>{togglePeople(false);$(window.innerWidth<=640?'mobile-search-button':'show-people').focus();});
  $('panel-scrim').addEventListener('click',()=>togglePeople(false));
  $('back').addEventListener('click',()=>{if(activeSection!=='tree')setSection('tree');else closeDetails();});
  $('export-svg').addEventListener('click',exportSvg);
  $('export-json').addEventListener('click',()=>{download(JSON.stringify(treeData,null,2),'application/json','family-tree.json');$('map-status').textContent=ui.jsonSaved;});
  for(const id of ['open-help','legend-help'])$(id).addEventListener('click',()=>{document.querySelector('.download-menu').open=false;$('help-dialog').showModal();});
  document.querySelectorAll('[data-close-dialog]').forEach((button)=>button.addEventListener('click',()=>$(button.dataset.closeDialog).close()));
  $('path-form').addEventListener('submit',(event)=>{event.preventDefault();$('path-dialog').close();showPath();});
  viewport.addEventListener('wheel',(event)=>{if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();const rect=viewport.getBoundingClientRect();setScale(scale*Math.exp(-event.deltaY*.008),event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
  viewport.addEventListener('pointerdown',(event)=>{
    if(event.pointerType!=='mouse'||event.button!==0||event.target.closest('.person,.edge'))return;
    const rect=viewport.getBoundingClientRect();if(event.clientX-rect.left>=viewport.clientWidth||event.clientY-rect.top>=viewport.clientHeight)return;
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};$('map-caption').hidden=true;viewport.setPointerCapture(event.pointerId);viewport.classList.add('dragging');viewport.focus({preventScroll:true});
  });
  viewport.addEventListener('pointermove',(event)=>{if(!drag||drag.id!==event.pointerId)return;viewport.scrollLeft=drag.left-(event.clientX-drag.x);viewport.scrollTop=drag.top-(event.clientY-drag.y);});
  const endDrag=()=>{drag=null;viewport.classList.remove('dragging');};
  viewport.addEventListener('pointerup',endDrag);viewport.addEventListener('pointercancel',endDrag);viewport.addEventListener('lostpointercapture',endDrag);
  viewport.addEventListener('keydown',(event)=>{if(event.target!==viewport)return;if(event.key==='+'||event.key==='='){event.preventDefault();setScale(scale*1.25);}if(event.key==='-'){event.preventDefault();setScale(scale/1.25);}if(event.key==='Home'){event.preventDefault();fitPeople([...visibleIds].map((id)=>people.get(id)));}});
  document.addEventListener('keydown',(event)=>{if(event.key!=='Escape'||document.querySelector('dialog[open]'))return;if($('people-panel').classList.contains('open')){togglePeople(false);$('search').focus();}else closeDetails();});
  let resizeTimer,compact=window.innerWidth<=980;
  window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(compact!==(window.innerWidth<=980)){compact=window.innerWidth<=980;togglePeople(!compact&&!selectedId);}if(activeSection==='tree'&&!viewport.hidden){const focus=selectedId||viewFocusId;if(visibleIds.has(focus))centerPerson(people.get(focus));else fitPeople([...visibleIds].map((id)=>people.get(id)));}},100);});
}

initializeCopy();renderGraph();renderPeople();initializeControls();applyView();togglePeople(window.innerWidth>980);document.body.classList.add('js');
document.fonts.ready.then(()=>{renderGraph();applyView();if(selectedId)highlight(selectedId);});
requestAnimationFrame(()=>{fitPeople(treeData.people);if(scale<.55)centerPerson(people.get(rootId));});
