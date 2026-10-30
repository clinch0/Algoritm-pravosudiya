// Run with Node: exercises real browser export, no DOM dependency.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const sandbox = {sessionStorage:{getItem:()=>null}, document:{addEventListener:()=>{}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('app/static/app.js','utf8'), sandbox);
const payload = {case_id:'T', masked_text:'SECRET', parameters:{masked_text:'SECRET', evidence:{text:'SECRET'},crime_date:'12.03.2024'}, similar:[{summary:'SECRET'}], stats:{edition:{crime_date:'12.03.2024'}}, conclusion:{similar:[{summary:'SECRET'}],stats:{edition:{crime_date:'12.03.2024'}},deeper_analysis:['Дата преступления: 12.03.2024','Keep this finding']}};
const result = sandbox.minimizedReport(payload);
assert(!JSON.stringify(result).includes('SECRET'));
assert(!JSON.stringify(result).includes('12.03.2024'));
assert(JSON.stringify(result).includes('Keep this finding'));
assert.equal(payload.parameters.crime_date,'12.03.2024');
const form = sandbox.recheckFormHtml({crime_date:'12.03.2024',rule_context:{special_order:true}});
assert(form.includes('name="crime_date"'));
assert(form.includes('name="ctx_special_order"'));
console.log('Browser projection and context form: passed');
