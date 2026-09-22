const fs = require('fs');
const crypto = require('crypto');
const root = 'C:/Users/ELadmin/Desktop/program/kimiclaw-monitor-messages';

// 1) skillHash of monitor-requirements block
const t = fs.readFileSync(root + '/skills/intranet-message-triage/SKILL.md', 'utf8');
const re = new RegExp('```json monitor-requirements\\r?\\n([\\s\\S]*?)\\r?\\n```');
const m = t.match(re);
if (!m) { console.log('BLOCK NOT FOUND'); process.exit(1); }
const block = m[1].trim();
console.log('skillHash=' + crypto.createHash('sha256').update(block, 'utf8').digest('hex'));
console.log('len=' + block.length);

// 2) error log lines after offset 5
const errFile = root + '/logs/intranet-error/2026-09-11.log';
const lines = fs.readFileSync(errFile, 'utf8').split(/\r?\n/).filter(l => l.trim());
console.log('errorTotalLines=' + lines.length);
console.log('linesAfterOffset5:');
lines.slice(5).forEach(l => console.log(l));

// 3) diff files after cursor
const diffDir = root + '/logs/intranet-diff';
const cursor = '2026-09-14_10-35-27-560.log';
const diffs = fs.readdirSync(diffDir).filter(f => f > cursor).sort();
console.log('pendingDiffs=' + diffs.length);
diffs.forEach(f => console.log('  ' + f));

// 4) check notify log for today
const today = '2026-09-14';
const nf = root + '/logs/intranet-notify/' + today + '.log';
if (fs.existsSync(nf)) {
  const nl = fs.readFileSync(nf, 'utf8').split(/\r?\n/).filter(l => l.trim());
  console.log('notifyLogLines=' + nl.length);
  nl.slice(-5).forEach(l => console.log('  notify> ' + l));
} else {
  console.log('notifyLogLines=0 (no file)');
}
