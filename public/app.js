const socket = io(); // Connects to the same host that serves the page

// UI Elements
const bossContainer = document.getElementById('boss-container');
const bossName = document.getElementById('boss-name');
const hpBarFill = document.getElementById('hp-bar-fill');
const hpText = document.getElementById('hp-text');
const bossChargeContainer = document.getElementById('boss-charge-container');
const bossChargeRing = document.getElementById('boss-charge-ring');
const bossChargeTime = document.getElementById('boss-charge-time');
const bossChargeAttack = document.getElementById('boss-charge-attack');
const bossChargeType = document.getElementById('boss-charge-type');
const bossChargeFill = document.getElementById('boss-charge-fill');

const logList = document.getElementById('log-list');

const artShowcase = document.getElementById('art-showcase');
const artImage = document.getElementById('art-image');
const artPrompt = document.getElementById('art-prompt');
const artCreator = document.getElementById('art-creator');

const partyContainer = document.getElementById('party-container');
const partyList = document.getElementById('party-list');

const inspectContainer = document.getElementById('inspect-container');

// URL Query parameter filtering for standalone browser sources
const urlParams = new URLSearchParams(window.location.search);
const showParam = urlParams.get('show'); // Supported: party, boss, combat, art, inspect, weapon

if (showParam) {
    // Hide everything by default
    const combatLog = document.getElementById('combat-log');
    if (combatLog) combatLog.classList.add('hidden');
    if (bossContainer) bossContainer.classList.add('hidden');
    if (partyContainer) partyContainer.classList.add('hidden');
    if (artShowcase) artShowcase.classList.add('hidden');
    if (inspectContainer) inspectContainer.classList.add('hidden');
    const weaponStandalone = document.getElementById('weapon-standalone-container');
    if (weaponStandalone) weaponStandalone.classList.add('hidden');
    const challengeBox = document.getElementById('challenge-box');
    if (challengeBox) challengeBox.classList.add('hidden');

    // Show only the requested one
    let target = null;
    if (showParam === 'party') target = partyContainer;
    else if (showParam === 'boss') target = bossContainer;
    else if (showParam === 'combat') target = combatLog;
    else if (showParam === 'art') target = artShowcase;
    else if (showParam === 'inspect') target = inspectContainer;
    else if (showParam === 'weapon') target = weaponStandalone;
    else if (showParam === 'challenge') target = challengeBox;

    if (target) {
        // If it's boss, art, inspect, weapon, or challenge, we let their socket listeners handle showing them,
        // but for party and combat log we can show them immediately.
        if (showParam === 'party' || showParam === 'combat') {
            target.classList.remove('hidden');
        }
        document.body.className = `standalone-${showParam}`;
    }
}

// Socket Events
socket.on('boss_update', (bossData) => {
    if (showParam && showParam !== 'boss') return;
    if (!bossData || bossData.status !== 'active') {
        bossContainer.classList.add('hidden');
        hideBossCharge();
        return;
    }

    bossContainer.classList.remove('hidden');
    bossName.innerText = bossData.name;

    const bossImage = document.getElementById('boss-image');
    if (bossData.image_url) {
        bossImage.src = bossData.image_url + "?t=" + new Date().getTime();
        bossImage.classList.remove('hidden');
    } else {
        bossImage.classList.add('hidden');
    }

    // Update HP Bar
    const percent = Math.max(0, (bossData.current_hp / bossData.max_hp) * 100);
    hpBarFill.style.width = `${percent}%`;
    hpText.innerText = `${bossData.current_hp} / ${bossData.max_hp}`;

    // Update Boss Stars
    const bossStarsEl = document.getElementById('boss-stars');
    if (bossStarsEl) {
        const starCount = bossData.stars || 1;
        bossStarsEl.innerHTML = '⭐'.repeat(starCount);
    }
});

let bossChargeInterval = null;
function hideBossCharge() {
    if (bossChargeInterval) {
        clearInterval(bossChargeInterval);
        bossChargeInterval = null;
    }
    if (bossChargeContainer) {
        bossChargeContainer.classList.add('hidden');
        bossChargeContainer.classList.remove('charge-physical', 'charge-magic', 'charge-piercing');
    }
}

socket.on('boss_charging', (data) => {
    if (showParam && showParam !== 'boss') return;
    if (!bossChargeContainer) return;

    const duration = Math.max(1, Number(data.duration || 20));
    const startedAt = Date.now();
    const attackName = data.attack_name || 'Incoming Attack';
    let attackType = (data.attack_type || 'physical').toLowerCase();
    if (!['physical', 'magic', 'piercing'].includes(attackType)) {
        attackType = 'physical';
    }

    bossChargeContainer.classList.remove('hidden', 'charge-physical', 'charge-magic', 'charge-piercing');
    bossChargeContainer.classList.add(`charge-${attackType}`);
    bossChargeAttack.innerText = attackName;
    bossChargeType.innerText = attackType.toUpperCase();

    if (bossChargeInterval) clearInterval(bossChargeInterval);

    const renderCharge = () => {
        const elapsed = (Date.now() - startedAt) / 1000;
        const remaining = Math.max(0, duration - elapsed);
        const progress = Math.max(0, Math.min(1, remaining / duration));
        const percent = progress * 100;

        bossChargeTime.innerText = remaining.toFixed(1);
        bossChargeFill.style.width = `${percent}%`;
        bossChargeRing.style.setProperty('--charge-progress', `${percent}%`);

        if (remaining <= 0) {
            hideBossCharge();
        }
    };

    renderCharge();
    bossChargeInterval = setInterval(renderCharge, 100);
});

socket.on('boss_defeated', (data) => {
    if (showParam && showParam !== 'boss' && showParam !== 'combat') return;
    hideBossCharge();

    const li = document.createElement('li');
    let content = `<strong>🏆 Boss Defeated by ${data.winner}!</strong>`;

    if (data.gold_rewards && data.gold_rewards.length > 0) {
        content += `<br><span class="loot-title">💰 ส่วนแบ่ง Gold:</span><br>` +
            data.gold_rewards.map(g => ` &nbsp;&nbsp;• ${g.character_name}: +${g.amount.toLocaleString()}G`).join('<br>');
    }

    if (data.drops && data.drops.length > 0) {
        content += `<br><span class="loot-title">🎁 Loot Drops:</span><br>` +
            data.drops.map(d => ` &nbsp;&nbsp;• ${d}`).join('<br>');
    }

    li.innerHTML = content;
    logList.appendChild(li);
    const combatLog = document.getElementById('combat-log');
    if (combatLog) combatLog.scrollTop = combatLog.scrollHeight;

    if (!showParam || showParam === 'boss') {
        hpBarFill.style.width = '0%';
        hpText.innerText = `0 / Boss HP`;
        setTimeout(() => {
            bossContainer.classList.add('hidden');
        }, 5000);
    }
});

socket.on('combat_event', (data) => {
    if (showParam && showParam !== 'combat') return;
    const li = document.createElement('li');
    const critSpan = data.is_crit ? '<span style="color:#f39c12; font-weight:bold;">[CRIT]</span> ' : '';
    li.innerHTML = `<em>${data.username}</em> used <strong>${data.action}</strong>! ${critSpan}Dealt ${data.damage} DMG.`;

    logList.appendChild(li);
    if (logList.children.length > 7) {
        logList.removeChild(logList.firstChild);
    }
    const combatLog = document.getElementById('combat-log');
    if (combatLog) combatLog.scrollTop = combatLog.scrollHeight;
});

let hideArtTimeout = null;
socket.on('show_art', (data) => {
    if (showParam && showParam !== 'art') return;
    artImage.src = data.image_url + "?t=" + new Date().getTime(); // Prevent caching
    artPrompt.innerText = data.prompt;
    artCreator.innerText = `By ${data.username} (${data.bits} Bits)`;

    artShowcase.classList.remove('hidden');

    if (hideArtTimeout) clearTimeout(hideArtTimeout);
    hideArtTimeout = setTimeout(() => {
        artShowcase.classList.add('hidden');
    }, 45000); // Hide after 45 seconds
});

// Parse URL layout mode parameters
const layoutMode = urlParams.get('mode') || 'auto'; // Supported: auto, normal, compact, ultra-compact, grid, scroll, carousel
const CAROUSEL_PAGE_SIZE = 3;

let currentPartyData = [];
let carouselInterval = null;
let carouselPage = 0;

function renderParty() {
    partyList.innerHTML = '';

    // Clear dynamic classes
    partyContainer.classList.remove('compact', 'ultra-compact', 'grid-mode');

    const count = currentPartyData.length;
    let modeToUse = layoutMode;

    if (modeToUse === 'auto') {
        if (count > 7) {
            modeToUse = 'ultra-compact';
        } else if (count > 4) {
            modeToUse = 'compact';
        } else {
            modeToUse = 'normal';
        }
    }

    // Reset carousel interval if not in carousel/scroll mode
    const isCarousel = (modeToUse === 'carousel' || modeToUse === 'scroll');
    if (!isCarousel && carouselInterval) {
        clearInterval(carouselInterval);
        carouselInterval = null;
    }

    let displayPlayers = [...currentPartyData];

    if (isCarousel) {
        const totalPages = Math.ceil(count / CAROUSEL_PAGE_SIZE);
        if (totalPages > 1) {
            if (!carouselInterval) {
                carouselPage = 0;
                carouselInterval = setInterval(() => {
                    carouselPage = (carouselPage + 1) % totalPages;
                    renderParty();
                }, 5000); // switch page every 5 seconds
            }
            const startIndex = carouselPage * CAROUSEL_PAGE_SIZE;
            displayPlayers = currentPartyData.slice(startIndex, startIndex + CAROUSEL_PAGE_SIZE);
            const titleElem = document.querySelector('.party-title');
            if (titleElem) titleElem.innerText = `Party (${carouselPage + 1}/${totalPages})`;
        } else {
            if (carouselInterval) {
                clearInterval(carouselInterval);
                carouselInterval = null;
            }
            const titleElem = document.querySelector('.party-title');
            if (titleElem) titleElem.innerText = 'Party';
        }
    } else {
        const titleElem = document.querySelector('.party-title');
        if (titleElem) titleElem.innerText = 'Party';
    }

    // Apply CSS classes to container
    if (modeToUse === 'compact') {
        partyContainer.classList.add('compact');
    } else if (modeToUse === 'ultra-compact') {
        partyContainer.classList.add('ultra-compact');
    } else if (modeToUse === 'grid') {
        partyContainer.classList.add('grid-mode');
    }

    displayPlayers.forEach(player => {
        const card = document.createElement('div');
        card.className = `party-card ${player.class}`;
        if (player.is_dead) {
            card.classList.add('dead');
        }
        if (player.is_defending) {
            card.classList.add('defending');
        }

        const hpPct = Math.max(0, Math.min(100, (player.hp / player.max_hp) * 100));
        const mpPct = Math.max(0, Math.min(100, (player.mp / player.max_mp) * 100));

        let badgeHtml = '';
        if (player.is_dead) {
            badgeHtml += `<span class="badge badge-dead">☠️ Dead</span>`;
        }
        if (player.is_defending) {
            badgeHtml += `<span class="badge badge-defending">🛡️ Defending</span>`;
        }

        card.innerHTML = `
            <div class="party-card-header">
                <div class="player-info">
                    <span class="class-icon">${player.icon}</span>
                    <span class="player-name">${player.character_name}</span>
                </div>
                <span class="player-level">Lv.${player.level}</span>
            </div>
            <div class="status-bars">
                <div class="bar-container">
                    <div class="bar-fill hp-fill" style="width: ${hpPct}%"></div>
                    <span class="bar-text">HP: ${player.hp} / ${player.max_hp}</span>
                </div>
                <div class="bar-container">
                    <div class="bar-fill mp-fill" style="width: ${mpPct}%"></div>
                    <span class="bar-text">MP: ${player.mp} / ${player.max_mp}</span>
                </div>
            </div>
            ${badgeHtml ? `<div class="status-badges">${badgeHtml}</div>` : ''}
        `;
        partyList.appendChild(card);
    });
}

socket.on('party_update', (partyData) => {
    if (showParam && showParam !== 'party') return;
    if (!partyData || partyData.length === 0) {
        partyContainer.classList.add('hidden');
        currentPartyData = [];
        if (carouselInterval) {
            clearInterval(carouselInterval);
            carouselInterval = null;
        }
        return;
    }

    partyContainer.classList.remove('hidden');
    currentPartyData = partyData;
    renderParty();
});

let hideInspectTimeout = null;
socket.on('inspect_player', (data) => {
    if (!data) return;

    // Determine what to show based on showParam
    if (showParam !== 'inspect' && showParam !== 'weapon') {
        return;
    }

    if (showParam === 'inspect') {
        inspectContainer.classList.remove('hidden');
    }

    // Populate profile data
    document.getElementById('inspect-name').innerText = data.character_name || data.username;
    document.getElementById('inspect-class-icon').innerText = data.icon || '⚔️';
    document.getElementById('inspect-level').innerText = `Lv.${data.level || 1}`;

    // Helper to format slot
    const updateSlot = (slotType, itemData) => {
        const imgEl = document.getElementById(`inspect-${slotType}-img`);
        const nameEl = document.getElementById(`inspect-${slotType}-name`);
        const enhEl = document.getElementById(`inspect-${slotType}-enh`);
        const frameEl = imgEl.parentElement;

        // Reset classes on the frame
        frameEl.className = 'slot-item-frame';

        imgEl.classList.remove('hidden');
        if (itemData) {
            imgEl.src = `images/items/${itemData.item_id}.png?t=` + new Date().getTime();
            imgEl.onerror = () => {
                // If specific item image is missing, try default empty placeholder
                imgEl.src = `images/items/empty_${slotType}.png`;
                imgEl.onerror = () => {
                    // If placeholder is also missing, hide image cleanly to avoid broken icon
                    imgEl.classList.add('hidden');
                    imgEl.onerror = null;
                };
            };

            // Show enhancement level clearly in the item name text underneath
            const nameText = itemData.enhancement_level > 0 ? `${itemData.name} +${itemData.enhancement_level}` : itemData.name;
            nameEl.innerText = nameText;
            enhEl.innerText = itemData.enhancement_level > 0 ? `+${itemData.enhancement_level}` : '';

            // Apply tier and enhancement glow classes
            if (itemData.tier) {
                frameEl.classList.add(`tier-${itemData.tier.toLowerCase()}`);
            }
            if (itemData.enhancement_level) {
                frameEl.classList.add(`enh-${itemData.enhancement_level}`);
                if (itemData.enhancement_level >= 7) {
                    frameEl.classList.add('glow-high');
                } else if (itemData.enhancement_level >= 4) {
                    frameEl.classList.add('glow-medium');
                }
            }
        } else {
            imgEl.src = `images/items/empty_${slotType}.png`;
            imgEl.onerror = () => {
                imgEl.classList.add('hidden');
                imgEl.onerror = null;
            };
            nameEl.innerText = 'Empty';
            enhEl.innerText = '';
        }
    };

    updateSlot('weapon', data.equipped_weapon);
    updateSlot('armor', data.equipped_armor);
    updateSlot('accessory', data.equipped_accessory);

    // Handle standalone weapon mode image update
    const weaponStandalone = document.getElementById('weapon-standalone-container');
    const weaponStandaloneImg = document.getElementById('weapon-standalone-image');
    if (weaponStandalone && weaponStandaloneImg) {
        if (data.equipped_weapon) {
            weaponStandaloneImg.src = `images/items/${data.equipped_weapon.item_id}.png?t=` + new Date().getTime();
            weaponStandaloneImg.onerror = () => {
                weaponStandaloneImg.src = '';
                weaponStandalone.classList.add('hidden');
            };
            if (showParam === 'weapon') {
                weaponStandalone.classList.remove('hidden');
            }
        } else {
            weaponStandaloneImg.src = '';
            weaponStandalone.classList.add('hidden');
        }
    }

    // Auto-hide inspect panel/standalone weapon after 15 seconds unless in pure inspect mode
    if (showParam !== 'inspect') {
        if (hideInspectTimeout) clearTimeout(hideInspectTimeout);
        hideInspectTimeout = setTimeout(() => {
            if (showParam === 'weapon') {
                if (weaponStandalone) weaponStandalone.classList.add('hidden');
            } else {
                inspectContainer.classList.add('hidden');
            }
        }, 15000);
    }
});

socket.on('challenge_update', (challengeData) => {
    if (showParam && showParam !== 'challenge') return;
    const challengeBox = document.getElementById('challenge-box');
    if (!challengeBox) return;

    if (!challengeData || challengeData.status === 'expired') {
        challengeBox.classList.add('hidden');
        return;
    }

    challengeBox.classList.remove('hidden');

    const descEl = document.getElementById('challenge-desc');
    const barFillEl = document.getElementById('challenge-bar-fill');
    const barTextEl = document.getElementById('challenge-bar-text');
    const rewardEl = document.getElementById('challenge-reward');

    if (descEl) descEl.innerText = challengeData.description;

    if (rewardEl) {
        let rewardText = "";
        const amt = challengeData.reward_amount.toLocaleString();
        if (challengeData.reward_type === 'gold') {
            rewardText = `💰 ${amt} Gold`;
        } else if (challengeData.reward_type === 'exp') {
            rewardText = `✨ ${amt} EXP`;
        } else if (challengeData.reward_type === 'both') {
            rewardText = `💰 ${amt} Gold & ✨ ${amt} EXP`;
        } else {
            rewardText = `${amt} ${challengeData.reward_type}`;
        }
        rewardEl.innerText = rewardText;
    }

    const cur = challengeData.current_value;
    const tgt = challengeData.target_value;
    const percent = Math.min(100, Math.max(0, (cur / tgt) * 100));

    if (barFillEl) {
        barFillEl.style.width = `${percent}%`;
    }
    if (barTextEl) {
        barTextEl.innerText = `${cur.toLocaleString()} / ${tgt.toLocaleString()} (${percent.toFixed(1)}%)`;
    }

    if (challengeData.status === 'completed') {
        challengeBox.classList.add('completed');
    } else {
        challengeBox.classList.remove('completed');
    }
});


