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
let diagram = null;


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
  .edge-label{font:11px 'Golos Text',Arial,sans-serif;fill:#4f5b57;pointer-events:none}
  .edge-caption{cursor:pointer;outline:none}.edge-caption rect{fill:#efeadf}
  .edge-caption:focus-visible rect,.edge-caption:hover rect{stroke:#1d5c57;stroke-width:1.5}
  .edge-caption.spiritual .edge-label{fill:#6a4e79}
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

function layoutDiagram(data) {
  if(!data.people.length)return {positions:new Map(),routes:new Map(),sections:[],width:data.width,height:data.height};
  const rows=[...new Set(data.people.map((p)=>p.y))].sort((a,b)=>a-b);
  const originals=new Map(data.people.map((p)=>[p.id,p]));
  const lanes=rows.map(()=>[]),entries=new Map(),ports=new Map();
  const w=data.cardWidth,h=data.cardHeight,pitch=56;
  let width=data.width;
  for(const edge of data.relationships){
    const a=originals.get(edge.from),b=originals.get(edge.to);
    const direct=['spouse','partner'].includes(edge.kind)&&a.y===b.y&&Math.abs(a.x-b.x)<=w+60;
    const entry={edge,direct,gap:rows.indexOf(Math.min(a.y,b.y))};entries.set(edge.id,entry);
    if(direct)continue;
    for(const [node,other] of [[a,b],[b,a]]){
      const side=other.y<node.y?'top':'bottom',key=node.id+':'+side;
      if(!ports.has(key))ports.set(key,[]);
      ports.get(key).push({edge:edge.id,otherX:other.x});
    }
  }
  for(const list of ports.values())list.sort((a,b)=>a.otherX-b.otherX||a.edge.localeCompare(b.edge));
  const routed=[...entries.values()].filter((e)=>!e.direct).sort((a,b)=>{
    const left=(e)=>Math.min(originals.get(e.edge.from).x,originals.get(e.edge.to).x);
    return left(a)-left(b)||a.edge.id.localeCompare(b.edge.id);
  });
  for(const entry of routed){
    const a=originals.get(entry.edge.from),b=originals.get(entry.edge.to);
    const interval=[Math.min(a.x,b.x)-12,Math.max(a.x,b.x)+w+12];
    const rowLanes=lanes[entry.gap];let lane=rowLanes.findIndex((items)=>items.every(([left,right])=>interval[1]<left||interval[0]>right));
    if(lane<0){lane=rowLanes.length;rowLanes.push([]);}
    rowLanes[lane].push(interval);entry.lane=lane;
  }
  const rowY=[rows[0]];
  for(let i=1;i<rows.length;i++)rowY[i]=rowY[i-1]+h+Math.max(152,lanes[i-1].length*pitch+60);
  const positions=new Map(data.people.map((p)=>[p.id,{x:p.x,y:rowY[rows.indexOf(p.y)]}]));
  const verticals=[],routes=new Map();
  function port(node,other,entry){
    const side=other.y<node.y?'top':'bottom',list=ports.get(node.id+':'+side);
    const index=list.findIndex((item)=>item.edge===entry.edge.id),position=positions.get(node.id);
    const desired=node.x+12+(index+1)*(w-24)/(list.length+1);
    const y=position.y+(side==='bottom'?h:0),rail=rowY[entry.gap]+h+36+entry.lane*pitch;
    const top=Math.min(y,rail),bottom=Math.max(y,rail);
    for(let step=0;step<=w;step+=12)for(const shift of step?[step,-step]:[0]){
      const x=desired+shift;if(x<node.x+12||x>node.x+w-12)continue;
      const blocked=verticals.some((v)=>Math.abs(v.x-x)<10&&Math.max(top,v.top)<Math.min(bottom,v.bottom)-.1)||data.people.some((p)=>{
        if(p.id===node.id)return false;const q=positions.get(p.id);
        return x>q.x-4&&x<q.x+w+4&&top<q.y+h-1&&bottom>q.y+1;
      });
      if(!blocked){verticals.push({x,top,bottom});return [x,y];}
    }
    return null;
  }
  for(const entry of routed){
    const a=originals.get(entry.edge.from),b=originals.get(entry.edge.to);
    const checkpoint=verticals.length;
    const start=port(a,b,entry),end=port(b,a,entry),rail=rowY[entry.gap]+h+36+entry.lane*pitch;
    if(start&&end){routes.set(entry.edge.id,{points:[start,[start[0],rail],[end[0],rail],end],rail});continue;}
    // A link across a filled row needs a channel outside the cards.
    verticals.length=checkpoint;
    const A=positions.get(a.id),B=positions.get(b.id),aTop=b.y<a.y,bTop=a.y<b.y;
    const ax=A.x+w/2,bx=B.x+w/2,ay=A.y+(aTop?0:h),by=B.y+(bTop?0:h);
    const aRail=ay+(aTop?-16:16),bRail=by+(bTop?-16:16),outside=width+32;width=outside+32;
    const points=[[ax,ay],[ax,aRail],[outside,aRail],[outside,bRail],[bx,bRail],[bx,by]];
    for(let i=1;i<points.length;i++)if(points[i-1][0]===points[i][0])verticals.push({x:points[i][0],top:Math.min(points[i-1][1],points[i][1]),bottom:Math.max(points[i-1][1],points[i][1])});
    routes.set(entry.edge.id,{points,rail:aRail});
  }
  for(const entry of entries.values())if(entry.direct){
    const a=positions.get(entry.edge.from),b=positions.get(entry.edge.to),left=a.x<b.x?a:b,right=a.x<b.x?b:a;
    routes.set(entry.edge.id,{points:[[left.x+w,left.y+h/2],[right.x,right.y+h/2]]});
  }
  const sections=data.sections.map((section)=>{
    const index=rows.findIndex((y)=>y>=section.y);
    return {...section,y:rowY[index<0?rows.length-1:index]-24};
  });
  return {positions,routes,sections,width,height:rowY.at(-1)+h+Math.max(100,lanes.at(-1).length*pitch+60)};
}

function edgePath(edge) {
  return diagram.routes.get(edge.id).points.map(([x,y],i)=>`${i?'L':'M'}${x},${y}`).join(' ');
}

function placeDiagramLabels() {
  const occupied=[],segments=[];
  for(const route of diagram.routes.values())for(let i=1;i<route.points.length;i++)segments.push([route.points[i-1],route.points[i]]);
  const cards=[...diagram.positions.values()].map((p)=>({x:p.x-8,y:p.y-8,width:cardW+16,height:cardH+16}));
  const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
  const clear=(box)=>!cards.some((card)=>overlaps(box,card))&&!occupied.some((other)=>overlaps(box,{x:other.x-6,y:other.y-6,width:other.width+12,height:other.height+12}))&&!segments.some(([[x1,y1],[x2,y2]])=>{
    if(Math.abs(x1-x2)<.1)return x1>box.x-4&&x1<box.x+box.width+4&&Math.min(y1,y2)<box.y+box.height+4&&Math.max(y1,y2)>box.y-4;
    return y1>box.y-4&&y1<box.y+box.height+4&&Math.min(x1,x2)<box.x+box.width+4&&Math.max(x1,x2)>box.x-4;
  });
  function place(text,font,size,idealX,ys,left,right){
    const lines=wrap(text,Math.max(80,Math.min(240,right-left-20)),font);textMeasure.font=font;
    const metrics=lines.map((line)=>textMeasure.measureText(line));
    const ascent=Math.max(...metrics.map((m)=>m.fontBoundingBoxAscent||m.actualBoundingBoxAscent||size));
    const descent=Math.max(3,...metrics.map((m)=>m.fontBoundingBoxDescent||m.actualBoundingBoxDescent||3));
    const lineHeight=Math.max(size+3,ascent+descent);
    const width=Math.max(...metrics.map((m)=>m.width))+12,height=ascent+descent+(lines.length-1)*lineHeight+8;
    const xs=[];for(let x=Math.max(8,left);x+width<=Math.min(diagram.width-8,right);x+=12)xs.push(x);
    xs.push(Math.max(left+8,Math.min(idealX,right-width-8)));
    const candidates=ys.flatMap((y)=>xs.map((x)=>({x,y:y-height,width,height}))).sort((a,b)=>Math.abs(a.x-idealX)+2*Math.abs(a.y-(ys[0]-height))-Math.abs(b.x-idealX)-2*Math.abs(b.y-(ys[0]-height)));
    const box=candidates.find((candidate)=>candidate.y>=8&&candidate.y+height<diagram.height&&clear(candidate));
    if(!box&&(left>8||right<diagram.width-8))return place(text,font,size,idealX,ys,8,diagram.width-8);
    if(!box)throw new Error('No clear caption position: '+text);
    occupied.push(box);return {...box,lines,size,ascent,lineHeight};
  }
  function draw(parent,box,className){
    parent.append(element('rect',{x:box.x,y:box.y,width:box.width,height:box.height,rx:3,fill:'#efeadf'}));
    const label=element('text',{x:box.x+6,y:box.y+box.ascent+4,class:className});
    box.lines.forEach((line,i)=>label.append(element('tspan',{x:box.x+6,dy:i?box.lineHeight:0},line+(i<box.lines.length-1?' ':''))));parent.append(label);
  }
  for(const section of diagram.sections){
    const box=place(section.text,'500 22px Literata, Georgia, serif',22,section.x,[section.y,section.y-28,section.y-56,section.y-84],8,diagram.width-8);
    const group=element('g',{'data-section-label':section.text});draw(group,box,'graph-section');$('sections').append(group);
  }
  for(const edge of drawnRelationships){
    const caption=edge.kind==='sibling'?ui.siblingLine:edge.kind==='unplaced'?(edge.label??ui.unplacedLine):edge.kind==='step'?ui.stepLine:null;
    if(!caption)continue;
    const route=diagram.routes.get(edge.id),left=Math.min(route.points[1][0],route.points[2][0]),right=Math.max(route.points[1][0],route.points[2][0]);
    const ideal=edge.labelX??(left+right)/2;
    const box=place(caption,"11px 'Golos Text', Arial, sans-serif",11,ideal-90,[route.rail-8,route.rail+46],left+6,right-6);
    const group=element('g',{id:'label-'+edge.id,class:'edge-caption '+edge.status,'data-edge-label':edge.id,role:'button',tabindex:0,'aria-label':caption});draw(group,box,'edge-label');
    group.addEventListener('click',()=>showRelationship(edge));group.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showRelationship(edge);}});
    $('edge-labels').append(group);
  }
}

function renderGraph() {
  diagram=layoutDiagram({...treeData,relationships:drawnRelationships});
  if(!$('edge-labels'))svg.insertBefore(element('g',{id:'edge-labels'}),$('nodes'));
  svg.insertBefore($('sections'),$('edge-labels'));
  svg.setAttribute('viewBox', `0 0 ${diagram.width} ${diagram.height}`);
  svg.querySelector(':scope > rect')?.remove();
  svg.insertBefore(element('rect', {x:0,y:0,width:diagram.width,height:diagram.height,fill:'#efeadf'}),svg.firstChild);
  for (const id of ['sections','edge-labels','edges','nodes']) $(id).replaceChildren();
  for (const edge of drawnRelationships) {
    const title=`${ui.relationNames[edge.kind]}: ${fullName(people.get(edge.from))}, ${fullName(people.get(edge.to))}. ${ui[edge.status]}`;
    const group=element('g',{class:`edge ${edge.status} ${edge.kind}`,'data-edge':edge.id,role:'button',tabindex:'0','aria-label':title});
    group.append(element('title',{},title+(edge.note?'. '+edge.note:'')));
    for (const className of ['edge-underlay','edge-line','edge-hit']) group.append(element('path',{d:edgePath(edge),class:className}));
    group.addEventListener('click',()=>showRelationship(edge));
    group.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showRelationship(edge);}});
    $('edges').append(group);
  }
  for (const person of treeData.people) {
    const isRoot=person.id===rootId;
    const position=diagram.positions.get(person.id);
    const group=element('g',{class:'person'+(isRoot?' root':''),'data-id':person.id,'data-family':person.family,transform:`translate(${position.x} ${position.y})`,role:'button',tabindex:'0','aria-label':`${fullName(person)}. ${person.role}. ${person.life}`});
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
  placeDiagramLabels();
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
  surface.style.width = diagram.width * scale + 'px'; surface.style.height = diagram.height * scale + 'px';
  svg.setAttribute('width', diagram.width * scale); svg.setAttribute('height', diagram.height * scale);
  const offset = surfaceOffset();
  viewport.scrollLeft = x * scale + offset.x - anchorX; viewport.scrollTop = y * scale + offset.y - anchorY;
  $('zoom-value').textContent = Math.round(scale * 100) + '%';
}

function surfaceOffset() {
  return {x:Math.max(0,viewport.clientWidth-diagram.width*scale)/2,y:Math.max(0,viewport.clientHeight-diagram.height*scale)/2};
}

function fitPeople(items) {
  if(!items.length){$('map-status').textContent=ui.emptyView;return;}
  items=items.length===people.size
    ? [{x:0,y:0},{x:diagram.width-cardW,y:diagram.height-cardH}]
    : items.map((person)=>diagram.positions.get(person.id));
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
  const position=diagram.positions.get(person.id);
  setScale(Math.max(scale,.9));
  const offset=surfaceOffset();
  viewport.scrollLeft=(position.x+cardW/2)*scale+offset.x-viewport.clientWidth/2;
  viewport.scrollTop=(position.y+cardH/2)*scale+offset.y-viewport.clientHeight/2;
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
  exported.setAttribute('xmlns',ns); exported.setAttribute('width',diagram.width);exported.setAttribute('height',diagram.height);
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
  document.querySelectorAll('.edge-caption').forEach((node)=>{const edge=svg.querySelector(`[data-edge="${CSS.escape(node.dataset.edgeLabel)}"]`);for(const state of ['view-hidden','is-filtered'])node.classList.toggle(state,edge.classList.contains(state));});
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
    if(event.pointerType!=='mouse'||event.button!==0||event.target.closest('.person,.edge,.edge-caption'))return;
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
