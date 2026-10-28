// Run with: node --test tests/test_tree_layout.cjs
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const {test} = require('node:test');

const source = readFileSync(join(__dirname, '../assets/family-tree/app.js'), 'utf8');
const layout = runInNewContext('(' + source.slice(source.indexOf('function layoutDiagram('), source.indexOf('\nfunction edgePath(')) + ')');
function data(people, relationships = []) {
  return {people, relationships, sections: [], width: 800, height: 700, cardWidth: 224, cardHeight: 128};
}
function checkRoutes(input, result) {
  assert.equal(result.routes.size, input.relationships.length);
  for (const edge of input.relationships) {
    const points = result.routes.get(edge.id).points;
    for (let i = 1; i < points.length; i++) {
      const [x1, y1] = points[i - 1], [x2, y2] = points[i];
      assert.ok(x1 === x2 || y1 === y2, edge.id + ' must be orthogonal');
      for (const person of input.people) {
        if (person.id === edge.from || person.id === edge.to) continue;
        const p = result.positions.get(person.id);
        const crosses = x1 === x2
          ? x1 > p.x && x1 < p.x + input.cardWidth && Math.min(y1, y2) < p.y + input.cardHeight && Math.max(y1, y2) > p.y
          : y1 > p.y && y1 < p.y + input.cardHeight && Math.min(x1, x2) < p.x + input.cardWidth && Math.max(x1, x2) > p.x;
        assert.equal(crosses, false, edge.id + ' crosses ' + person.id);
      }
    }
  }
}

test('empty case keeps finite dimensions', () => {
  const result = layout(data([]));
  assert.equal(result.positions.size, 0);
  assert.equal(result.routes.size, 0);
  assert.equal(result.width, 800);
  assert.equal(result.height, 700);
});

test('adjacent spouses keep their direct connector', () => {
  const input = data([{id: 'a', x: 56, y: 100}, {id: 'b', x: 328, y: 100}], [{id: 'r', from: 'a', to: 'b', kind: 'spouse'}]);
  const result = layout(input);
  assert.equal(result.routes.get('r').points.length, 2);
  checkRoutes(input, result);
});

test('overlapping connector spans use separate lanes', () => {
  const input = data([{id: 'a', x: 56, y: 100}, {id: 'b', x: 328, y: 100}, {id: 'c', x: 56, y: 340}, {id: 'd', x: 328, y: 340}],
    [{id: 'r1', from: 'a', to: 'd', kind: 'parent'}, {id: 'r2', from: 'b', to: 'c', kind: 'parent'}, {id: 'r3', from: 'a', to: 'c', kind: 'parent'}]);
  const result = layout(input);
  assert.equal(new Set([...result.routes.values()].map(r => r.rail)).size, 3);
  assert.ok(result.positions.get('c').y > 340);
  checkRoutes(input, result);
});

test('a connector that skips a filled row goes around its card', () => {
  const input = data([{id: 'a', x: 56, y: 100}, {id: 'b', x: 56, y: 340}, {id: 'c', x: 56, y: 580}],
    [{id: 'r1', from: 'a', to: 'b', kind: 'parent'}, {id: 'r2', from: 'b', to: 'c', kind: 'parent'}, {id: 'r3', from: 'a', to: 'c', kind: 'unplaced'}]);
  const result = layout(input);
  assert.ok(result.width > input.width);
  checkRoutes(input, result);
});
