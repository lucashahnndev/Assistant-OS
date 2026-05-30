const total = 5;
const bs = {x: 100, y: 0, z: 0};
let bnx = 1, bny = 1, bnz = 1;
const vol = bs.x * bs.y * bs.z || 1;
const k = Math.pow(total / vol, 1/3);
bnx = Math.max(1, Math.round(bs.x * k));
bny = Math.max(1, Math.round(bs.y * k));
bnz = Math.max(1, Math.round(bs.z * k));
while (bnx * bny * bnz < total) {
    if (bnx <= bny && bnx <= bnz) bnx++;
    else if (bny <= bnx && bny <= bnz) bny++;
    else bnz++;
}
console.log({bnx, bny, bnz});
