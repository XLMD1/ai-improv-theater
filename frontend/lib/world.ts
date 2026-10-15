import type {PublicWorld,World} from './types';

export function normalizeWorld(value:PublicWorld):World {
  return {title:value.title,version:value.story_version,investigation:true,setting:value.setting,era:value.era,intro:value.intro,
    scenes:Object.fromEntries(value.locations.map(location=>[location.id,{name:location.name,background:''}])),
    characters:Object.fromEntries(value.cast.map(person=>[person.id,{name:person.name,
      role:person.id===value.protagonist_id?'你的角色':'人物',goal:person.appearance,portrait:''}])),
    objects:value.objects,evidence:value.evidence,disclosures:value.disclosures,commitments:value.commitments,ending:value.ending};
}
