import assert from 'node:assert/strict';
import {test} from 'node:test';
import {normalizeWorld} from '../lib/world.ts';

test('investigation worlds use server location and character IDs and discovered evidence',()=>{
 const world=normalizeWorld({story_id:'story',story_version:'1',title:'古城',setting:'古代河运',era:'ancient',intro:'公开简介',
  location:{id:'courtyard',name:'庭院',description:'院落'},locations:[{id:'courtyard',name:'庭院',description:'院落'}],
  characters:[{id:'witness',name:'证人',appearance:'布衣'}],cast:[{id:'player',name:'主角',appearance:'青衣'},{id:'witness',name:'证人',appearance:'布衣'}],
  protagonist_id:'player',objects:[{id:'box',name:'木箱',description:'旧箱'}],evidence:[{id:'letter',description:'已发现的信件'}],
  disclosures:[],commitments:[],ending:null});
 assert.equal(world.scenes.courtyard.name,'庭院');assert.equal(world.characters.witness.name,'证人');
 assert.ok(!('c1' in world.characters));assert.equal(world.evidence[0].id,'letter');assert.equal(world.investigation,true);
});
