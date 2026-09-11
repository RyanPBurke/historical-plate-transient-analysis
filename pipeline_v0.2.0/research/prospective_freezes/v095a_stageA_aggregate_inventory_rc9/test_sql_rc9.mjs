import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { PGlite } from '@electric-sql/pglite';

// Synthetic metadata and measurements only. No archive service is queried.
const db = new PGlite();
const sql = readFileSync(new URL('./v095a_stageA_queries_rc9.sql', import.meta.url), 'utf8');
const extract = family => {
  const begin = `-- BEGIN ${family}`;
  const end = `-- END ${family}`;
  assert.equal(sql.split(begin).length - 1, 1);
  assert.equal(sql.split(end).length - 1, 1);
  return sql.split(begin)[1].split(end)[0].trim();
};

const rowTable = (template, placeholder, columns, rows) => {
  assert.equal(template.split(placeholder).length - 1, 1);

  const relation = rows.map((row, i) =>
    '    SELECT ' +
    row.map((v, j) =>
      String(v) + (i === 0 ? ` AS ${columns[j]}` : '')
    ).join(', ')
  ).join('\n    UNION ALL\n');

  return template.replace(placeholder, relation);
};

const q0 = extract('Q0_SELECTED_SOLUTION_BINDING');
const q1 = extract('Q1_SELECTED_SCIENCE_KEY_AGGREGATES');
const q2 = extract('Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY');

assert.equal(/\bWITH\s+(wanted|selected|plates)\b/.test(sql), false);
assert.equal(sql.includes(' FILTER ('), false);

await db.exec(`
CREATE SCHEMA applause_dr4;
CREATE TABLE applause_dr4.solution (
 solution_id integer, plate_id integer, scan_id integer,
 process_id integer, solution_num smallint, solutionset_id integer
);
CREATE TABLE applause_dr4.source_calib (
 plate_id integer, scan_id integer, process_id integer, solution_num smallint,
 gaiaedr3_id bigint, sextractor_flags smallint, model_prediction real,
 ra_error real, dec_error real, ra_icrs double precision,
 dec_icrs double precision, annular_bin smallint
);
INSERT INTO applause_dr4.solution VALUES (1001,101,201,301,1,401);
`);
const binding = await db.query(rowTable(
  q0,
  '/*__Q0_VALUES__*/',
  ['key_id','solution_id','expected_plate_id','expected_scan_id'],
  [[1,1001,101,201],[2,1002,102,202]]
));
assert.deepEqual(binding.rows.map(r=>r.solution_row_found),[1,0]);
assert.equal(binding.rows[1].process_id,null);
assert.deepEqual([binding.rows[0].returned_plate_id,binding.rows[0].returned_scan_id,
 binding.rows[0].process_id,binding.rows[0].solution_num],[101,201,301,1]);
console.log('Q0 synthetic valid/missing binding: PASS');

const scalar = x => x===null ? 'NULL' : typeof x==='string' ? `'${x}'` : String(x);
const prediction = [null,-1,0,0.05,0.10,0.49,0.50,0.89,0.90,0.98,0.99,1,2,'NaN','Infinity','-Infinity'];
const errors = [null,-1,0,0.125,0.25,0.375,0.50,0.75,1,1.5,2,3,5,7,10,11,'NaN','Infinity','-Infinity'];
const coordinates = [[null,null],[null,0],[0,null],[0,0],[359.9,90],[0,-90],[360,0],[-1,0],[0,91],[0,-91],['NaN',0],[0,'NaN'],['Infinity',0],[0,'-Infinity']];
const annuli = [null,0,1,2,3,4,5,6,7,8,9,10,-1];
const integers = [null,-1,0,1];
const n = 19;
const rows = [];
for(let i=0;i<n;i++){
  const [ra,dec] = coordinates[i%coordinates.length];
  rows.push([101,201,301,1,integers[i%4],integers[(i+1)%4],prediction[i%prediction.length],errors[i],errors[n-i-1],ra,dec,annuli[i%annuli.length]]);
}
// A real row with NULL measurements must count once in every NULL category.
rows.push([103,203,303,1,...Array(8).fill(null)]);
// Vary each science-key component independently: none may leak into Q1.
for(const key of [[104,201,301,1],[101,999,301,1],[101,201,999,1],[101,201,301,2]])
 rows.push([...key,...Array(8).fill(null)]);
await db.exec('INSERT INTO applause_dr4.source_calib VALUES '+rows.map(r=>'('+r.map(scalar).join(',')+')').join(',')+';');
const inventory = await db.query(rowTable(
  q1,
  '/*__Q1_VALUES__*/',
  ['key_id','plate_id','scan_id','process_id','solution_num'],
  [[1,101,201,301,1],[2,102,202,302,1],[3,103,203,303,1]]
));
assert.deepEqual(inventory.rows.map(r=>Number(r.source_rows)),[n,0,1]);
const families = ['gaia_','sexflag_','mp_','raerr_','decerr_','coord_','annular_'];
for(const row of inventory.rows){
  for(const family of families){
    const total=Object.entries(row).filter(([k])=>k.startsWith(family)).reduce((a,[,v])=>a+Number(v),0);
    assert.equal(total,Number(row.source_rows),`${row.key_id}: ${family}`);
  }
}
for(const key of ['gaia_null','sexflag_null','mp_null','raerr_null','decerr_null','coord_both_null','annular_null'])assert.equal(Number(inventory.rows[2][key]),1);
const expectedErrors=[1,2,1,2,2,2,2,2,2,3];
const errorSuffixes=['null','lt0','eq0','0_025','025_050','050_100','100_200','200_500','500_1000','gt1000'];
for(const prefix of ['raerr_','decerr_'])
 assert.deepEqual(errorSuffixes.map(k=>Number(inventory.rows[0][prefix+k])),expectedErrors);
assert.deepEqual(['both_null','ra_null_only','dec_null_only','valid_icrs_bounds','out_of_bounds']
 .map(k=>Number(inventory.rows[0]['coord_'+k])),[2,2,2,5,8]);
console.log('Q1 selected-key isolation, absent key, real NULL row, bin boundaries/NaN/infinity completeness: PASS');

const original = await db.query(rowTable(
  q2,
  '/*__Q2_VALUES__*/',
  ['plate_id'],
  [[101],[102],[103]]
));
const empty = original.rows.find(r=>r.plate_id===102);
assert.equal(Number(empty.all_processing_source_rows),0);
assert.equal(Number(empty.distinct_scans),0);
assert.equal(Number(empty.distinct_processes),0);
assert.equal(Number(empty.distinct_process_solution_nums),0);
assert.equal(Number(empty.distinct_scan_process_solution_nums),0);
console.log('Q2 RC9 empty-plate result:',JSON.stringify(empty));

const populated=original.rows.find(r=>r.plate_id===101);
assert.deepEqual(['all_processing_source_rows','distinct_scans','distinct_processes',
 'distinct_process_solution_nums','distinct_scan_process_solution_nums']
 .map(k=>Number(populated[k])),[22,2,2,3,4]);
// Negative regression: an unguarded composite tuple on an unmatched
// LEFT JOIN row counts the all-NULL composite as one in PostgreSQL/PGlite.
const broken = await db.query(`
SELECT
  p.plate_id,
  COUNT(DISTINCT (sc.process_id, sc.solution_num))
    AS distinct_process_solution_nums,
  COUNT(DISTINCT (sc.scan_id, sc.process_id, sc.solution_num))
    AS distinct_scan_process_solution_nums
FROM (SELECT 102 AS plate_id) AS p
LEFT JOIN applause_dr4.source_calib AS sc
  ON sc.plate_id = p.plate_id
GROUP BY p.plate_id
`);

assert.equal(Number(broken.rows[0].distinct_process_solution_nums),1);
assert.equal(Number(broken.rows[0].distinct_scan_process_solution_nums),1);

console.log('Q2 empty plate all zero, populated multiplicity, unguarded-tuple negative regression: PASS');
console.log('Engine:',(await db.query('SELECT version() AS version')).rows[0].version);
await db.close();
