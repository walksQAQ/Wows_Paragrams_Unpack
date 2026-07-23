(function () {
  const {
    angleSweep,
    clockwiseDelta,
    normalizeAngle,
    svgNumber,
  } = globalThis.MKShipUtils || {};

  function rotateSector(sector, degrees) {
    if (!sector) return null;
    return {
      start: sector.start + degrees,
      end: sector.end + degrees,
    };
  }

  function mirrorHorizontalSector(sector) {
    if (!sector) return null;
    const start = -sector.end;
    const end = -sector.start;
    return {
      start: Math.abs(start) < 0.001 ? 0 : start,
      end: Math.abs(end) < 0.001 ? 0 : end,
    };
  }

  function splitSectorByDeadZones(sector, deadZones = []) {
    if (!sector) return [];
    const sectorSweep = angleSweep(sector.start, sector.end);
    if (sectorSweep >= 359.9 && !deadZones.length) return [sector];
    const blocks = [];
    deadZones.forEach((deadZone) => {
      const deadSweep = angleSweep(deadZone.start, deadZone.end);
      if (deadSweep >= 359.9) {
        blocks.push({ start: 0, end: sectorSweep });
        return;
      }
      const deadStart = clockwiseDelta(sector.start, deadZone.start);
      [-360, 0, 360].forEach((shift) => {
        const start = deadStart + shift;
        const end = start + deadSweep;
        const overlapStart = Math.max(0, start);
        const overlapEnd = Math.min(sectorSweep, end);
        if (overlapEnd - overlapStart > 0.001) {
          blocks.push({ start: overlapStart, end: overlapEnd });
        }
      });
    });
    if (!blocks.length) return [sector];

    const mergedBlocks = blocks
      .sort((left, right) => left.start - right.start || left.end - right.end)
      .reduce((merged, block) => {
        const previous = merged[merged.length - 1];
        if (previous && block.start <= previous.end + 0.001) {
          previous.end = Math.max(previous.end, block.end);
        } else {
          merged.push({ ...block });
        }
        return merged;
      }, []);

    const pieces = [];
    let cursor = 0;
    mergedBlocks.forEach((block) => {
      if (block.start - cursor > 0.001) {
        pieces.push({ start: sector.start + cursor, end: sector.start + block.start });
      }
      cursor = Math.max(cursor, block.end);
    });
    if (sectorSweep - cursor > 0.001) {
      pieces.push({ start: sector.start + cursor, end: sector.start + sectorSweep });
    }
    return pieces;
  }

  function uniqueAngleValues(angles) {
    const unique = [];
    angles.forEach((angle) => {
      const normalized = normalizeAngle(angle);
      if (!unique.some((existing) => Math.abs(normalizeAngle(existing) - normalized) < 0.001)) {
        unique.push(angle);
      }
    });
    return unique;
  }

  function sectorLabelAngles(sector, deadZones = []) {
    if (!sector) return [];
    const sectorSweep = angleSweep(sector.start, sector.end);
    if (sectorSweep >= 359.9) {
      return uniqueAngleValues(deadZones.flatMap((deadZone) => [deadZone.start, deadZone.end]));
    }
    return uniqueAngleValues([sector.start, sector.end]);
  }

  function sectorPieceLabelAngles(sectors) {
    return uniqueAngleValues((sectors || []).flatMap((sector) => [sector.start, sector.end]));
  }

  function signedAngle(degrees) {
    const normalized = normalizeAngle(degrees);
    return normalized > 180 ? normalized - 360 : normalized;
  }

  function sectorCrossesForwardCenterline(sector) {
    if (!sector) return false;
    const sweep = angleSweep(sector.start, sector.end);
    if (sweep >= 220) return false;
    const offsetToForward = clockwiseDelta(sector.start, 0);
    return offsetToForward > 0.001 && offsetToForward < sweep - 0.001;
  }

  function sectorSideSign(sector) {
    if (!sector) return null;
    const sweep = angleSweep(sector.start, sector.end);
    if (sweep >= 220) return 0;
    const midpoint = normalizeAngle(sector.start + sweep / 2);
    const centerlineDistance = Math.min(
      Math.abs(midpoint),
      Math.abs(midpoint - 180),
      Math.abs(midpoint - 360),
    );
    if (centerlineDistance <= 6) return 0;
    return midpoint < 180 ? 1 : -1;
  }

  function polarPoint(cx, cy, radius, degrees) {
    const radians = normalizeAngle(degrees) * Math.PI / 180;
    return {
      x: cx + Math.sin(radians) * radius,
      y: cy - Math.cos(radians) * radius,
    };
  }

  function sectorPath(cx, cy, radius, sector) {
    if (!sector) return "";
    const sweep = angleSweep(sector.start, sector.end);
    if (sweep >= 359.9) {
      return [
        `M ${svgNumber(cx)} ${svgNumber(cy)}`,
        `L ${svgNumber(cx)} ${svgNumber(cy - radius)}`,
        `A ${radius} ${radius} 0 1 1 ${svgNumber(cx)} ${svgNumber(cy + radius)}`,
        `A ${radius} ${radius} 0 1 1 ${svgNumber(cx)} ${svgNumber(cy - radius)}`,
        "Z",
      ].join(" ");
    }
    const start = polarPoint(cx, cy, radius, sector.start);
    const end = polarPoint(cx, cy, radius, sector.end);
    return [
      `M ${svgNumber(cx)} ${svgNumber(cy)}`,
      `L ${svgNumber(start.x)} ${svgNumber(start.y)}`,
      `A ${radius} ${radius} 0 ${sweep > 180 ? 1 : 0} 1 ${svgNumber(end.x)} ${svgNumber(end.y)}`,
      "Z",
    ].join(" ");
  }

  function sectorContainsAngle(sector, degrees) {
    if (!sector) return false;
    const sectorSweep = clockwiseDelta(sector.start, sector.end);
    if (sectorSweep < 0.001) return true;
    return clockwiseDelta(sector.start, degrees) <= sectorSweep + 0.001;
  }

  globalThis.MKShipGeometry = {
    mirrorHorizontalSector,
    polarPoint,
    rotateSector,
    sectorContainsAngle,
    sectorCrossesForwardCenterline,
    sectorLabelAngles,
    sectorPath,
    sectorPieceLabelAngles,
    sectorSideSign,
    signedAngle,
    splitSectorByDeadZones,
    uniqueAngleValues,
  };
}());
