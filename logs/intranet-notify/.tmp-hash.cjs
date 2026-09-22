const fs = require('fs');
const crypto = require('crypto');
const s = fs.readFileSync('skills/intranet-message-triage/SKILL.md', 'utf8');
const m = s.match(/```json monitor-requirements\n([\s\S]*?)```/);
if (!m) { console.error('block not found'); process.exit(1); }
const c = m[1].trim();
console.log(crypto.createHash('sha256').update(c, 'utf8').digest('hex'));
