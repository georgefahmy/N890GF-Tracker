/**
 * AeroFuel IQ — Airport Fuel Price Radar
 * High-performance spatial aviation fuel lookup and interactive radar
 * Supports 5,000+ public airports across all US states and territories
 */

(function () {
  'use strict';

  // --- Configuration & Defaults ---
  const STATE = {
    airports: [],
    airportsMap: new Map(),
    spatialGrid: new Map(), // "latBucket,lonBucket" -> Array of airports
    gridBucketSize: 1.0, // 1 degree lat/lon buckets (~69 miles)
    circleCenter: { lat: 37.5119, lng: -122.2495 }, // San Carlos KSQL / SF Bay Area default
    originAirport: null, // Origin reference airport object { icao, faa, name, city, state, lat, lon }
    destinationAirport: null, // Destination airport object { icao, faa, name, city, state, lat, lon }
    activeRoute: null, // Active calculated fuel route object
    activePopupIcao: null, // Currently open popup airport identifier (pinned against radius cull/removal)
    radarEnabled: true, // true = radar search active, false = radar turned off entirely
    radiusValue: 50, // default 50
    radiusUnit: 'mi', // 'mi' (statute miles), 'NM' (nautical miles), 'km'
    isLocked: false, // true = fixed circle, false = follows mouse
    selectedFuelType: 'all', // 'all', '100LL', '94UL', '100UL', '100R', 'Mogas'
    selectedService: 'any', // 'any', 'self', 'full'
    selectedPriceTier: 'all', // 'all', 'ultra-cheap', 'budget', 'avg', 'high', 'exp', 'priced-only', 'unpriced', 'no-fuel'
    activeAirportModal: null,
    selectedAirport: null, // User-selected airport for info card when radar is off or focused
    lowestAirport: null,
    airportsInRadius: [],
    markers: new Map(), // icao -> { marker, apt, tierClass, fuelInfo }
    activeHighlightedIcaos: new Set(),
    fetchedAirports: new Set(), // ICAOs that have been fetched via AirNav on-demand
    p20: 5.20,
    p40: 5.80,
    p60: 6.40,
    p80: 7.00,
    p25: 5.20,
    p75: 6.50,
    cachedPriceValues: [],
    customPrices: {}, // stored in localStorage / user sessions
    lastUpdated: null,
    dataSource: 'AeroFuel National GA Fuel Network / FAA Public Airfield Directory',
    prevLowestIcao: null,
    prevInRadiusIcaos: new Set(),
    prevSidebarSignature: '',
    prevBestDealSignature: ''
  };

  const PERSISTED_AIRPORTS_STORAGE_KEY = 'AEROFUEL_PERSISTED_AIRPORTS_V2';
  const ORIGIN_AIRPORT_STORAGE_KEY = 'AEROFUEL_ORIGIN_AIRPORT';

  function savePersistedAirportToStorage(apt) {
    if (!apt || !apt.icao) return;
    try {
      const raw = localStorage.getItem(PERSISTED_AIRPORTS_STORAGE_KEY);
      const store = raw ? JSON.parse(raw) : {};
      const cleanIcao = apt.icao.toUpperCase().trim();
      const cleanFaa = apt.faa ? apt.faa.toUpperCase().trim() : cleanIcao;
      const dataToSave = {
        icao: cleanIcao,
        faa: cleanFaa,
        iata: apt.iata || '',
        name: apt.name || `${cleanIcao} Airport`,
        city: apt.city || '',
        state: apt.state || '',
        country: apt.country || 'US',
        lat: apt.lat,
        lon: apt.lon,
        elevation_ft: apt.elevation_ft || 0,
        ctaf_freq: apt.ctaf_freq || 122.8,
        unicom_freq: apt.unicom_freq || 122.8,
        tower: apt.tower || false,
        runways: apt.runways || [],
        fbos: apt.fbos || [],
        best_price: apt.best_price,
        primary_fuel: apt.primary_fuel,
        fuels_available: apt.fuels_available || [],
        last_updated: apt.last_updated,
        fetched_at: apt.fetched_at || null,
        source: apt.source
      };
      store[cleanIcao] = dataToSave;
      if (cleanFaa && cleanFaa !== cleanIcao) {
        store[cleanFaa] = dataToSave;
      }
      localStorage.setItem(PERSISTED_AIRPORTS_STORAGE_KEY, JSON.stringify(store));
    } catch (e) {
      console.warn('Failed to save airport to localStorage:', e);
    }
  }

  function savePersistedAirportsBatchToStorage(airportsList) {
    if (!airportsList || airportsList.length === 0) return;
    try {
      const raw = localStorage.getItem(PERSISTED_AIRPORTS_STORAGE_KEY);
      const store = raw ? JSON.parse(raw) : {};
      for (let i = 0; i < airportsList.length; i++) {
        const apt = airportsList[i];
        if (apt && apt.icao) {
          const cleanIcao = apt.icao.toUpperCase().trim();
          const cleanFaa = apt.faa ? apt.faa.toUpperCase().trim() : cleanIcao;
          const dataToSave = {
            icao: cleanIcao,
            faa: cleanFaa,
            iata: apt.iata || '',
            name: apt.name || `${cleanIcao} Airport`,
            city: apt.city || '',
            state: apt.state || '',
            country: apt.country || 'US',
            lat: apt.lat,
            lon: apt.lon,
            elevation_ft: apt.elevation_ft || 0,
            ctaf_freq: apt.ctaf_freq || 122.8,
            unicom_freq: apt.unicom_freq || 122.8,
            tower: apt.tower || false,
            runways: apt.runways || [],
            fbos: apt.fbos || [],
            best_price: apt.best_price,
            primary_fuel: apt.primary_fuel,
            fuels_available: apt.fuels_available || [],
            last_updated: apt.last_updated,
            fetched_at: apt.fetched_at || null,
            source: apt.source
          };
          store[cleanIcao] = dataToSave;
          if (cleanFaa && cleanFaa !== cleanIcao) {
            store[cleanFaa] = dataToSave;
          }
        }
      }
      localStorage.setItem(PERSISTED_AIRPORTS_STORAGE_KEY, JSON.stringify(store));
    } catch (e) {
      console.warn('Failed to save batch airports to localStorage:', e);
    }
  }

  function applyPersistedAirportsFromStorage() {
    try {
      // Purge stale legacy unversioned storage key if present
      if (localStorage.getItem('AEROFUEL_PERSISTED_AIRPORTS')) {
        localStorage.removeItem('AEROFUEL_PERSISTED_AIRPORTS');
      }
      const raw = localStorage.getItem(PERSISTED_AIRPORTS_STORAGE_KEY);
      if (!raw) return;
      const store = JSON.parse(raw);
      for (const [icao, savedApt] of Object.entries(store)) {
        const cleanIcao = icao.toUpperCase().trim();
        let target = STATE.airportsMap.get(cleanIcao);
        if (target) {
          target.fbos = savedApt.fbos || [];
          target.best_price = savedApt.best_price;
          target.primary_fuel = savedApt.primary_fuel;
          target.fuels_available = savedApt.fuels_available || [];
          target.last_updated = savedApt.last_updated;
          target.fetched_at = savedApt.fetched_at || target.fetched_at || null;
          target.source = savedApt.source || target.source;
          if (savedApt.ctaf_freq) target.ctaf_freq = savedApt.ctaf_freq;
          if (savedApt.unicom_freq) target.unicom_freq = savedApt.unicom_freq;
          if (savedApt.tower !== undefined) target.tower = savedApt.tower;
          if (savedApt.runways && savedApt.runways.length > 0) target.runways = savedApt.runways;
        } else if (savedApt.lat !== undefined && savedApt.lon !== undefined) {
          const newApt = Object.assign({}, savedApt);
          STATE.airports.push(newApt);
          STATE.airportsMap.set(cleanIcao, newApt);
          if (newApt.faa && newApt.faa !== cleanIcao) {
            STATE.airportsMap.set(newApt.faa.toUpperCase().trim(), newApt);
          }
        }

        // Mark as fetched and populate customPrices
        STATE.fetchedAirports.add(cleanIcao);
        if (savedApt.faa) {
          STATE.fetchedAirports.add(savedApt.faa.toUpperCase().trim());
        }
        if (!STATE.customPrices[cleanIcao]) {
          STATE.customPrices[cleanIcao] = {};
        }
        if (savedApt.fetched_at) {
          STATE.customPrices[cleanIcao].fetched_at = savedApt.fetched_at;
        }
        if (savedApt.faa) {
          const faaKey = savedApt.faa.toUpperCase().trim();
          if (!STATE.customPrices[faaKey]) {
            STATE.customPrices[faaKey] = {};
          }
          if (savedApt.fetched_at) {
            STATE.customPrices[faaKey].fetched_at = savedApt.fetched_at;
          }
        }
        if (savedApt.fbos && savedApt.fbos.length > 0) {
          for (let f = 0; f < savedApt.fbos.length; f++) {
            const fbo = savedApt.fbos[f];
            for (const [fkey, fval] of Object.entries(fbo.fuels || {})) {
              if (fval && fval.price !== undefined) {
                STATE.customPrices[cleanIcao][fkey] = fval.price;
                if (savedApt.faa) {
                  STATE.customPrices[savedApt.faa.toUpperCase().trim()][fkey] = fval.price;
                }
              }
            }
          }
        }
      }
    } catch (e) {
      console.warn('Failed to load persisted airports from localStorage:', e);
    }
  }

  // --- Origin Airport Persistence & Selection Helpers ---
  function setOriginAirport(identOrApt) {
    if (!identOrApt) {
      clearOriginAirport();
      return;
    }
    let apt = null;
    if (typeof identOrApt === 'string') {
      let clean = identOrApt.toUpperCase().trim();
      if (clean.startsWith('{')) {
        try {
          const parsed = JSON.parse(clean);
          clean = (parsed.icao || parsed.faa || '').toUpperCase().trim();
        } catch (e) {}
      }
      if (clean.includes('-')) {
        clean = clean.split('-')[0].trim();
      }
      if (clean.includes(' ')) {
        clean = clean.split(' ')[0].trim();
      }
      apt = STATE.airportsMap.get(clean);
      if (!apt && clean.startsWith('K') && clean.length === 4) {
        apt = STATE.airportsMap.get(clean.slice(1));
      } else if (!apt && clean.length === 3) {
        apt = STATE.airportsMap.get('K' + clean);
      }
    } else if (typeof identOrApt === 'object' && identOrApt !== null) {
      if (identOrApt.lat !== undefined && identOrApt.lon !== undefined) {
        apt = identOrApt;
      } else if (identOrApt.icao || identOrApt.faa) {
        const code = (identOrApt.icao || identOrApt.faa).toUpperCase().trim();
        apt = STATE.airportsMap.get(code) || (code.startsWith('K') ? STATE.airportsMap.get(code.slice(1)) : STATE.airportsMap.get('K' + code));
      }
    }

    if (apt) {
      STATE.originAirport = {
        icao: apt.icao,
        faa: apt.faa || apt.icao,
        iata: apt.iata || '',
        name: apt.name,
        city: apt.city,
        state: apt.state,
        lat: apt.lat,
        lon: apt.lon
      };
      try {
        localStorage.setItem(ORIGIN_AIRPORT_STORAGE_KEY, apt.icao);
      } catch (e) {
        console.warn('Failed to save origin airport to localStorage:', e);
      }
      updateOriginUI();
      updateOriginVectorLine();
      recalculateRadiusAirports();
      renderAllAirportMarkers();
      showToast(`🛫 Origin airport set to ${apt.faa || apt.icao} (${apt.name})`);
    }
  }

  function clearOriginAirport() {
    STATE.originAirport = null;
    try {
      localStorage.removeItem(ORIGIN_AIRPORT_STORAGE_KEY);
    } catch (e) {
      console.warn('Failed to clear origin airport from localStorage:', e);
    }
    updateOriginUI();
    updateOriginVectorLine();
    recalculateRadiusAirports();
    renderAllAirportMarkers();
    showToast('🛫 Origin airport reference cleared');
  }

  function updateOriginUI() {
    const input = document.getElementById('origin-airport-input');
    const clearBtn = document.getElementById('btn-clear-origin');
    if (input) {
      if (STATE.originAirport) {
        const ident = STATE.originAirport.faa || STATE.originAirport.icao;
        input.value = `${ident} - ${STATE.originAirport.name}`;
        if (clearBtn) clearBtn.style.display = 'flex';
      } else {
        input.value = '';
        if (clearBtn) clearBtn.style.display = 'none';
      }
    }
  }

  // --- Destination Airport Selection & Helpers ---
  function setDestinationAirport(identOrApt) {
    if (!identOrApt) {
      clearDestinationAirport();
      return;
    }
    let apt = null;
    if (typeof identOrApt === 'string') {
      let clean = identOrApt.toUpperCase().trim();
      if (clean.includes('-')) {
        clean = clean.split('-')[0].trim();
      }
      if (clean.includes(' ')) {
        clean = clean.split(' ')[0].trim();
      }
      apt = STATE.airportsMap.get(clean);
      if (!apt && clean.startsWith('K') && clean.length === 4) {
        apt = STATE.airportsMap.get(clean.slice(1));
      } else if (!apt && clean.length === 3) {
        apt = STATE.airportsMap.get('K' + clean);
      }
    } else if (typeof identOrApt === 'object' && identOrApt !== null) {
      if (identOrApt.lat !== undefined && identOrApt.lon !== undefined) {
        apt = identOrApt;
      } else if (identOrApt.icao || identOrApt.faa) {
        const code = (identOrApt.icao || identOrApt.faa).toUpperCase().trim();
        apt = STATE.airportsMap.get(code) || (code.startsWith('K') ? STATE.airportsMap.get(code.slice(1)) : STATE.airportsMap.get('K' + code));
      }
    }

    if (apt) {
      STATE.destinationAirport = {
        icao: apt.icao,
        faa: apt.faa || apt.icao,
        iata: apt.iata || '',
        name: apt.name,
        city: apt.city,
        state: apt.state,
        lat: apt.lat,
        lon: apt.lon
      };
      updateDestinationUI();
      recalculateRadiusAirports();
      renderAllAirportMarkers();
      showToast(`🛬 Destination airport set to ${apt.faa || apt.icao} (${apt.name})`);
    }
  }

  function clearDestinationAirport() {
    STATE.destinationAirport = null;
    updateDestinationUI();
    clearFuelRoute();
    showToast('🛬 Destination airport cleared');
  }

  function updateDestinationUI() {
    const input = document.getElementById('destination-airport-input');
    const clearBtn = document.getElementById('btn-clear-destination');
    if (input) {
      if (STATE.destinationAirport) {
        const ident = STATE.destinationAirport.faa || STATE.destinationAirport.icao;
        input.value = `${ident} - ${STATE.destinationAirport.name}`;
        if (clearBtn) clearBtn.style.display = 'flex';
      } else {
        input.value = '';
        if (clearBtn) clearBtn.style.display = 'none';
      }
    }
  }

  // --- AirNav Fuel Route Planning & Map Rendering ---
  async function planFuelRoute(selectedRouteIdx = 0) {
    if (!STATE.originAirport) {
      showToast('⚠️ Please specify an Origin Airport first (e.g. KSQL)');
      const originInput = document.getElementById('origin-airport-input');
      if (originInput) originInput.focus();
      return;
    }
    if (!STATE.destinationAirport) {
      showToast('⚠️ Please specify a Destination Airport (e.g. KDEN)');
      const destInput = document.getElementById('destination-airport-input');
      if (destInput) destInput.focus();
      return;
    }

    const originCode = STATE.originAirport.faa || STATE.originAirport.icao;
    const destCode = STATE.destinationAirport.faa || STATE.destinationAirport.icao;
    const rangeInput = document.getElementById('route-range-input');
    const rangeVal = rangeInput ? (parseInt(rangeInput.value, 10) || 400) : 400;

    const btnPlan = document.getElementById('btn-plan-route');
    if (btnPlan) {
      btnPlan.disabled = true;
      btnPlan.innerHTML = '<span>⏳ Planning...</span>';
    }

    try {
      const url = `/api/airnav/route?origin=${encodeURIComponent(originCode)}&destination=${encodeURIComponent(destCode)}&range=${rangeVal}&selected=${selectedRouteIdx}`;
      const res = await fetch(url);
      const data = await res.json();

      if (!res.ok || !data.success) {
        showToast(`⚠️ ${data.message || data.error || 'Failed to compute fuel route'}`);
        return;
      }

      STATE.activeRoute = data;
      renderRouteOnMap(data);
      renderRouteItinerary(data);
      updateOriginVectorLine(); // Re-snap vector to nearest route stop
      const btnClear = document.getElementById('btn-clear-route');
      if (btnClear) btnClear.style.display = 'block';

      showToast(`✈️ Route computed: ${data.route_string} (${data.total_distance || ''})`);
    } catch (err) {
      showToast(`⚠️ Fuel route calculation failed (${err.message}). Is server.py running?`);
    } finally {
      if (btnPlan) {
        btnPlan.disabled = false;
        btnPlan.innerHTML = '<span>✈️ Plan Route</span>';
      }
    }
  }

  function clearFuelRoute() {
    STATE.activeRoute = null;
    if (routeLayerGroup) {
      routeLayerGroup.clearLayers();
    }
    const hud = document.getElementById('route-itinerary-hud');
    if (hud) {
      hud.style.display = 'none';
      hud.innerHTML = '';
    }
    const btnClear = document.getElementById('btn-clear-route');
    if (btnClear) btnClear.style.display = 'none';
    updateOriginVectorLine(); // Restore vector back to origin airport
    recalculateRadiusAirports();
    renderAllAirportMarkers();
  }

  function renderRouteOnMap(routeData) {
    if (!routeLayerGroup || !map || !routeData || !routeData.stops || routeData.stops.length === 0) return;

    routeLayerGroup.clearLayers();

    const latLngs = [];
    const stops = routeData.stops;

    stops.forEach((stop, idx) => {
      let lat = stop.lat;
      let lon = stop.lon;

      // Fallback coordinate lookup from client DB
      if (lat === null || lon === null || lat === undefined || lon === undefined) {
        const apt = STATE.airportsMap.get(stop.airport_code) || STATE.airportsMap.get('K' + stop.airport_code);
        if (apt) {
          lat = apt.lat;
          lon = apt.lon;
          stop.lat = lat;
          stop.lon = lon;
        }
      }

      if (lat !== null && lon !== null && !isNaN(lat) && !isNaN(lon)) {
        latLngs.push([lat, lon]);
      }
    });

    if (latLngs.length > 1) {
      // Outer glow line
      const glowPolyline = L.polyline(latLngs, {
        color: '#38bdf8',
        weight: 7,
        opacity: 0.45,
        className: 'flight-path-glow',
        interactive: false
      });
      glowPolyline.addTo(routeLayerGroup);

      // Core crisp aviation line
      const corePolyline = L.polyline(latLngs, {
        color: '#0284c7',
        weight: 3.5,
        opacity: 0.95,
        interactive: false
      });
      corePolyline.addTo(routeLayerGroup);

      // Animated dashed overlay line
      const dashPolyline = L.polyline(latLngs, {
        color: '#ffffff',
        weight: 2,
        opacity: 0.8,
        dashArray: '8, 12',
        className: 'flight-path-dashed',
        interactive: false
      });
      dashPolyline.addTo(routeLayerGroup);

      // Smoothly pan & fit bounds to include entire flight path
      map.fitBounds(glowPolyline.getBounds(), {
        padding: [70, 70],
        maxZoom: 12
      });
    }

    // Refresh markers to render unified route waypoint badges
    recalculateRadiusAirports();
    renderAllAirportMarkers();
  }

  function renderRouteItinerary(routeData) {
    const hud = document.getElementById('route-itinerary-hud');
    if (!hud || !routeData) return;

    const stops = routeData.stops || [];
    let stopsHtml = '';

    stops.forEach((s, idx) => {
      const isFirst = idx === 0;
      const isLast = idx === stops.length - 1;
      const badgeText = isFirst ? '🛫' : (isLast ? '🛬' : `${idx}`);
      const priceText = (() => {
        if (!s.price) return '--';
        const num = parseFloat(String(s.price).replace(/[^0-9.]/g, ''));
        if (isNaN(num)) return s.price;
        const prefix = String(s.price).trimStart().startsWith('$') ? '$' : '';
        return `${prefix}${num.toFixed(2)}`;
      })();
      const legText = s.distance_to_next ? `${s.distance_to_next}` : (isLast ? 'Destination' : '');

      stopsHtml += `
        <div class="route-stop-item" data-code="${s.airport_code}">
          <div class="route-stop-info">
            <span class="route-stop-idx">${badgeText}</span>
            <div>
              <div class="route-stop-code">${s.airport_code}</div>
              <div class="route-stop-name">${s.airport_name || s.location || ''}</div>
            </div>
          </div>
          <div class="route-stop-metrics">
            <span class="route-stop-price">${priceText}</span>
            <span class="route-stop-leg">${legText}</span>
          </div>
        </div>
      `;
    });

    const savingsHtml = routeData.savings && routeData.savings > 0
      ? `<div class="route-stat-pill route-stat-savings">Est. Savings: <span class="route-stat-val">$${routeData.savings.toFixed(2)}</span></div>`
      : '';

    hud.innerHTML = `
      <div class="route-itinerary-header">
        <div class="route-itinerary-title">
          <span>✈️ Fuel Plan Itinerary</span>
        </div>
        <span style="font-size: 0.7rem; color: var(--text-dim);">${stops.length} Stops</span>
      </div>
      <div class="route-itinerary-stats">
        <div class="route-stat-pill">Dist: <span class="route-stat-val">${routeData.total_distance || '--'}</span></div>
        <div class="route-stat-pill">Max Leg: <span class="route-stat-val">${routeData.longest_leg || '--'}</span></div>
        ${savingsHtml}
      </div>
      <div class="route-stops-list">
        ${stopsHtml}
      </div>
    `;

    hud.style.display = 'block';

    hud.querySelectorAll('.route-stop-item').forEach(item => {
      item.addEventListener('click', function () {
        const code = this.getAttribute('data-code');
        const apt = STATE.airportsMap.get(code) || STATE.airportsMap.get('K' + code);
        if (apt) {
          map.flyTo([apt.lat, apt.lon], 10, { duration: 0.8 });
          openAirportPopup(apt, false);
        }
      });
    });
  }

  function applyPersistedOriginAirportFromStorage() {
    try {
      const savedIcao = localStorage.getItem(ORIGIN_AIRPORT_STORAGE_KEY);
      if (savedIcao) {
        let clean = savedIcao.toUpperCase().trim();
        if (clean.startsWith('{')) {
          try {
            const parsed = JSON.parse(clean);
            clean = (parsed.icao || parsed.faa || '').toUpperCase().trim();
          } catch (e) {}
        }
        const apt = STATE.airportsMap.get(clean) || (clean.startsWith('K') ? STATE.airportsMap.get(clean.slice(1)) : STATE.airportsMap.get('K' + clean));
        if (apt) {
          STATE.originAirport = {
            icao: apt.icao,
            faa: apt.faa || apt.icao,
            iata: apt.iata || '',
            name: apt.name,
            city: apt.city,
            state: apt.state,
            lat: apt.lat,
            lon: apt.lon
          };
          updateOriginUI();
          updateOriginVectorLine();
        }
      }
    } catch (e) {
      console.warn('Failed to restore origin airport from localStorage:', e);
    }
  }

  /**
   * Computes great-circle distance and initial bearing from active Origin Airport
   * to a target airport. Returns null if no Origin Airport is configured or if target is origin itself.
   */
  function getOriginDistanceInfo(apt) {
    if (!STATE.originAirport || !apt) return null;
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const originIcao = (STATE.originAirport.icao || '').toUpperCase().trim();
    const originFaa = (STATE.originAirport.faa || '').toUpperCase().trim();

    // If target airport is the origin airport itself, return null so badge doesn't show redundant 0.0 mi
    if ((cleanIcao && cleanIcao === originIcao) || (cleanFaa && cleanFaa === originFaa)) {
      return null;
    }

    const originLat = STATE.originAirport.lat;
    const originLon = STATE.originAirport.lon;
    const distMiles = haversineMiles(originLat, originLon, apt.lat, apt.lon);
    const bearing = calculateBearing(originLat, originLon, apt.lat, apt.lon);
    const originIdent = STATE.originAirport.faa || STATE.originAirport.icao;
    return {
      distMiles: distMiles,
      distFormatted: formatDistance(distMiles),
      bearing: bearing,
      direction: getCompassDirection(bearing),
      originIdent: originIdent,
      originName: STATE.originAirport.name
    };
  }

  /**
   * Computes route stop metadata if airport is part of the currently active flight route.
   * Returns { index, isFirst, isLast, label, price, distance_to_next, heading_to_next } or null.
   */
  function getRouteStopInfo(apt) {
    if (!STATE.activeRoute || !STATE.activeRoute.stops || STATE.activeRoute.stops.length === 0 || !apt) return null;
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const stops = STATE.activeRoute.stops;

    for (let idx = 0; idx < stops.length; idx++) {
      const stop = stops[idx];
      const stopCode = (stop.airport_code || '').toUpperCase().trim();
      if (cleanIcao === stopCode || cleanFaa === stopCode || (stopCode.startsWith('K') && (cleanFaa === stopCode.slice(1) || cleanIcao === stopCode.slice(1))) || ('K' + cleanFaa === stopCode) || ('K' + cleanIcao === stopCode)) {
        const isFirst = idx === 0;
        const isLast = idx === stops.length - 1;
        const badgeLabel = isFirst ? '🛫 START' : (isLast ? '🛬 END' : `🛑 STOP ${idx}`);
        return {
          index: idx,
          isFirst: isFirst,
          isLast: isLast,
          label: badgeLabel,
          price: stop.price,
          distance_to_next: stop.distance_to_next,
          heading_to_next: stop.heading_to_next
        };
      }
    }
    return null;
  }

  // Unit conversion multipliers to meters (for Leaflet circle)
  const UNIT_TO_METERS = {
    mi: 1609.344,
    NM: 1852.0,
    km: 1000.0
  };

  // Multiplier to statute miles (for calculation)
  const UNIT_TO_MILES = {
    mi: 1.0,
    NM: 1.15078,
    km: 0.621371
  };

  // Map & Overlay References
  let map = null;
  let radiusCircle = null;
  let centerReticleMarker = null;
  let vectorLine = null;
  let originVectorLine = null;
  let originVectorLabel = null;
  let markersLayerGroup = null;
  let routeLayerGroup = null;
  let animFrameId = null;
  let mousePendingPos = null;
  let airportCanvasEl = null;
  let airportCanvasCtx = null;
  let aeroScaleControl = null;
  let scaleToggleBtn = null;

  // --- Spatial Grid Indexing ---
  function buildSpatialGridIndex() {
    STATE.spatialGrid.clear();
    const size = STATE.gridBucketSize;
    for (let i = 0; i < STATE.airports.length; i++) {
      const apt = STATE.airports[i];
      const latB = Math.floor(apt.lat / size);
      const lonB = Math.floor(apt.lon / size);
      const key = `${latB},${lonB}`;
      let bucket = STATE.spatialGrid.get(key);
      if (!bucket) {
        bucket = [];
        STATE.spatialGrid.set(key, bucket);
      }
      bucket.push(apt);
    }
  }

  /**
   * Fast spatial grid bounding query.
   * Returns a small candidate subset of airports intersecting the radius circle bounding box.
   */
  function querySpatialCandidates(centerLat, centerLon, radiusMiles) {
    const latDelta = radiusMiles / 68.7;
    const minLat = Math.max(-89.9, centerLat - latDelta);
    const maxLat = Math.min(89.9, centerLat + latDelta);

    const maxAbsLat = Math.max(Math.abs(minLat), Math.abs(maxLat));
    const cosLat = Math.max(0.01, Math.cos(maxAbsLat * Math.PI / 180));
    const lonDelta = Math.min(180.0, radiusMiles / (68.7 * cosLat));

    const minLon = centerLon - lonDelta;
    const maxLon = centerLon + lonDelta;

    const size = STATE.gridBucketSize;
    const minLatB = Math.floor(minLat / size);
    const maxLatB = Math.floor(maxLat / size);
    const minLonB = Math.floor(minLon / size);
    const maxLonB = Math.floor(maxLon / size);

    const candidates = [];
    for (let latB = minLatB; latB <= maxLatB; latB++) {
      for (let lonB = minLonB; lonB <= maxLonB; lonB++) {
        const bucket = STATE.spatialGrid.get(`${latB},${lonB}`);
        if (bucket) {
          for (let k = 0; k < bucket.length; k++) {
            const a = bucket[k];
            // Fast bounding box check
            if (a.lat >= minLat && a.lat <= maxLat && a.lon >= minLon && a.lon <= maxLon) {
              candidates.push(a);
            }
          }
        }
      }
    }
    return candidates;
  }

  // --- Spatial Math Functions ---
  /**
   * Great circle distance using Haversine formula (returns statute miles)
   */
  function haversineMiles(lat1, lon1, lat2, lon2) {
    const R = 3958.8; // Earth radius in statute miles
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  /**
   * Initial bearing from point 1 to point 2 in degrees (0-360)
   */
  function calculateBearing(lat1, lon1, lat2, lon2) {
    const y = Math.sin((lon2 - lon1) * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180);
    const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180) -
              Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos((lon2 - lon1) * Math.PI / 180);
    const brng = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    return Math.round(brng);
  }

  function getCompassDirection(bearing) {
    const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const idx = Math.round(bearing / 22.5) % 16;
    return directions[idx];
  }

  /**
   * Converts distance in statute miles to the user's active display unit
   */
  function formatDistance(distMiles) {
    if (STATE.radiusUnit === 'NM') {
      return `${(distMiles / 1.15078).toFixed(1)} NM`;
    } else if (STATE.radiusUnit === 'km') {
      return `${(distMiles * 1.60934).toFixed(1)} km`;
    }
    return `${distMiles.toFixed(1)} mi`;
  }

  /**
   * Formats an ISO 8601 timestamp into a sleek relative time string (e.g. 'Just now', '15m ago', '3h ago', '2d ago').
   */
  function formatRelativeTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return '';
    const ageMs = Date.now() - date.getTime();
    if (ageMs < 0) return 'Just now';
    const ageSec = Math.floor(ageMs / 1000);
    if (ageSec < 60) return 'Just now';
    const ageMin = Math.floor(ageSec / 60);
    if (ageMin < 60) return `${ageMin}m ago`;
    const ageHours = Math.floor(ageMin / 60);
    if (ageHours < 24) return `${ageHours}h ago`;
    const ageDays = Math.floor(ageHours / 24);
    return `${ageDays}d ago`;
  }

  // --- Price Extraction & Filtering ---
  /**
   * Checks if an airport has active fetched live fuel prices in session state.
   */
  function hasFetchedPrice(airport) {
    if (!airport) return false;
    const cleanIcao = (airport.icao || '').toUpperCase().trim();
    const cleanFaa = (airport.faa || '').toUpperCase().trim();
    if (STATE.fetchedAirports) {
      if (cleanIcao && STATE.fetchedAirports.has(cleanIcao)) return true;
      if (cleanFaa && STATE.fetchedAirports.has(cleanFaa)) return true;
    }
    if (STATE.customPrices) {
      if (cleanIcao && STATE.customPrices[cleanIcao] && Object.keys(STATE.customPrices[cleanIcao]).length > 0) return true;
      if (cleanFaa && STATE.customPrices[cleanFaa] && Object.keys(STATE.customPrices[cleanFaa]).length > 0) return true;
    }
    if (airport.fbos && airport.fbos.length > 0) return true;
    if (airport.fetched_at || (airport.best_price !== null && airport.best_price !== undefined)) return true;
    return false;
  }

  /**
   * Computes the effective non-jet fuel price for an airport based on active filters.
   * Returns null if airport has not been fetched on demand or has no matching commercial fuel prices.
   */
  function getEffectiveFuelInfo(airport) {
    if (!airport) return null;
    const cleanIcao = (airport.icao || '').toUpperCase().trim();
    const cleanFaa = (airport.faa || '').toUpperCase().trim();
    const canonicalApt = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || airport;

    if (!hasFetchedPrice(canonicalApt)) {
      return null;
    }
    if (!canonicalApt.fbos || canonicalApt.fbos.length === 0) {
      if (canonicalApt.best_price && typeof canonicalApt.best_price === 'number' && canonicalApt.best_price > 0) {
        return {
          price: canonicalApt.best_price,
          type: canonicalApt.primary_fuel || '100LL',
          service: 'Self-Serve',
          label: `${canonicalApt.primary_fuel || '100LL'}`,
          fboName: 'Local FBO',
          phone: ''
        };
      }
      return null;
    }

    const custom = STATE.customPrices[cleanIcao] || (cleanFaa ? STATE.customPrices[cleanFaa] : null) || STATE.customPrices[airport.icao];
    const eligiblePrices = [];

    // Scan all FBOs at this airport
    for (let i = 0; i < canonicalApt.fbos.length; i++) {
      const fbo = canonicalApt.fbos[i];
      const fuels = fbo.fuels || {};
      for (const [fuelKey, fuelObj] of Object.entries(fuels)) {
        if (!fuelObj || fuelObj.price === undefined) continue;
        if (fuelObj.type === 'Jet-A' || fuelObj.type === 'SAF') continue; // Always ignore Jet-A and SAF for piston search

        // Filter by Fuel Type
        if (STATE.selectedFuelType !== 'all') {
          if (fuelObj.type !== STATE.selectedFuelType) continue;
        }

        // Filter by Service Type
        if (STATE.selectedService === 'self' && fuelObj.service !== 'Self-Serve') continue;
        if (STATE.selectedService === 'full' && fuelObj.service !== 'Full-Serve') continue;

        let price = fuelObj.price;
        if (custom && custom[fuelKey] !== undefined) {
          price = custom[fuelKey];
        }

        if (price && typeof price === 'number' && price > 0) {
          eligiblePrices.push({
            price: price,
            type: fuelObj.type,
            service: fuelObj.service,
            label: fuelObj.label || `${fuelObj.type} (${fuelObj.service})`,
            fboName: fbo.name,
            phone: fbo.phone
          });
        }
      }
    }

    if (eligiblePrices.length === 0) {
      return null;
    }

    // Sort to find lowest price for this airport
    eligiblePrices.sort((a, b) => a.price - b.price);
    return eligiblePrices[0];
  }

  /**
   * Evaluates if an airport/fuel matches the currently selected price quantile filter.
   */
  function matchesPriceTier(fuelInfo, isSearched) {
    const selected = STATE.selectedPriceTier || 'all';
    if (selected === 'all') return true;

    if (selected === 'priced-only') {
      return fuelInfo !== null && typeof fuelInfo.price === 'number';
    }
    if (selected === 'unpriced') {
      return fuelInfo === null;
    }
    if (selected === 'no-fuel') {
      return isSearched && fuelInfo === null;
    }

    if (!fuelInfo || typeof fuelInfo.price !== 'number') {
      return false;
    }

    const tierInfo = getFuelTierInfo(fuelInfo.price);
    return tierInfo && tierInfo.tier === selected;
  }

  /**
   * Returns comprehensive color, label, and style metadata for a fuel price based on 5-tier quintiles.
   */
  function getFuelTierInfo(price) {
    if (price === null || price === undefined || isNaN(price)) {
      return {
        tier: 'unpriced',
        tierClass: 'tier-ident',
        label: 'Unpriced',
        sublabel: 'Unfetched',
        color: '#64748b',
        priceColor: '#94a3b8',
        badgeBg: 'rgba(15, 23, 42, 0.88)',
        badgeBorder: 'rgba(148, 163, 184, 0.2)',
        glow: 'rgba(148, 163, 184, 0.3)',
        alpha: 0.55
      };
    }
    const p20 = STATE.p20 ?? 5.20;
    const p40 = STATE.p40 ?? 5.80;
    const p60 = STATE.p60 ?? 6.40;
    const p80 = STATE.p80 ?? 7.00;

    if (price <= p20) {
      return {
        tier: 'ultra-cheap',
        tierClass: 'tier-ultra-cheap',
        label: 'Ultra-Cheap',
        sublabel: 'Best Value (0–20%)',
        color: '#10b981', // Emerald Green
        priceColor: '#34d399',
        badgeBg: 'rgba(6, 78, 59, 0.92)',
        badgeBorder: '#10b981',
        glow: 'rgba(16, 185, 129, 0.5)',
        alpha: 0.90
      };
    } else if (price <= p40) {
      return {
        tier: 'budget',
        tierClass: 'tier-budget',
        label: 'Budget',
        sublabel: 'Cheap (20–40%)',
        color: '#06b6d4', // Cyan / Teal
        priceColor: '#22d3ee',
        badgeBg: 'rgba(8, 51, 68, 0.92)',
        badgeBorder: '#06b6d4',
        glow: 'rgba(6, 182, 212, 0.5)',
        alpha: 0.85
      };
    } else if (price <= p60) {
      return {
        tier: 'avg',
        tierClass: 'tier-avg',
        label: 'Moderate',
        sublabel: 'Average (40–60%)',
        color: '#38bdf8', // Sky Blue
        priceColor: '#38bdf8',
        badgeBg: 'rgba(15, 23, 42, 0.92)',
        badgeBorder: '#38bdf8',
        glow: 'rgba(56, 189, 248, 0.4)',
        alpha: 0.80
      };
    } else if (price <= p80) {
      return {
        tier: 'high',
        tierClass: 'tier-high',
        label: 'High',
        sublabel: 'Above Avg (60–80%)',
        color: '#f59e0b', // Amber / Orange
        priceColor: '#fbbf24',
        badgeBg: 'rgba(69, 26, 3, 0.92)',
        badgeBorder: '#f59e0b',
        glow: 'rgba(245, 158, 11, 0.5)',
        alpha: 0.85
      };
    } else {
      return {
        tier: 'exp',
        tierClass: 'tier-exp',
        label: 'Expensive',
        sublabel: 'Premium (80–100%)',
        color: '#ec4899', // Vivid Magenta / Fuchsia Pink
        priceColor: '#f472b6',
        badgeBg: 'rgba(80, 7, 36, 0.92)',
        badgeBorder: '#ec4899',
        glow: 'rgba(236, 72, 153, 0.55)',
        alpha: 0.90
      };
    }
  }

  // --- Tri-Unit Aviation Map Scale Control (mi, NM, km in Bottom-Left) ---
  function getNiceScaleNumber(maxUnits) {
    if (maxUnits <= 0) return 1;
    const pow10 = Math.pow(10, Math.floor(Math.log10(maxUnits)));
    const d = maxUnits / pow10;
    let factor = 1;
    if (d >= 5) {
      factor = 5;
    } else if (d >= 2) {
      factor = 2;
    } else {
      factor = 1;
    }
    const val = factor * pow10;
    return val >= 1 ? Math.round(val) : parseFloat(val.toPrecision(2));
  }

  const AeroScaleControl = L.Control.extend({
    options: {
      position: 'bottomright',
      maxWidth: 110,
      updateWhenIdle: false
    },

    onAdd: function (mapInstance) {
      this._map = mapInstance;
      const container = L.DomUtil.create('div', 'leaflet-control-aero-scale');
      this._container = container;
      this._buildDom();
      this._update();

      this._map.on('zoom', this._update, this);
      this._map.on('move', this._update, this);
      this._map.on('viewreset', this._update, this);
      this._map.on('resize', this._update, this);
      this._map.whenReady(this._update, this);

      return container;
    },

    onRemove: function () {
      if (this._map) {
        this._map.off('zoom', this._update, this);
        this._map.off('move', this._update, this);
        this._map.off('viewreset', this._update, this);
        this._map.off('resize', this._update, this);
      }
    },

    collapse: function () {
      if (this._container) {
        this._container.classList.add('scale-collapsed');
      }
      updateScaleButtonState(false);
    },

    expand: function () {
      if (this._container) {
        this._container.classList.remove('scale-collapsed');
      }
      updateScaleButtonState(true);
      this._update();
    },

    toggle: function () {
      if (this.isCollapsed()) {
        this.expand();
      } else {
        this.collapse();
      }
    },

    isCollapsed: function () {
      return this._container ? this._container.classList.contains('scale-collapsed') : false;
    },

    _buildDom: function () {
      this._container.innerHTML = `
        <div class="aero-scale-hud">
          <div class="aero-scale-header" id="aero-scale-header-toggle" title="Click to collapse scale">
            <div class="aero-scale-header-left">
              <span class="aero-scale-title">RADAR SCALE</span>
              <span class="aero-scale-lat-indicator" id="aero-scale-lat-ind">--°</span>
            </div>
            <button type="button" class="aero-scale-close-btn" id="aero-scale-close-btn" title="Collapse Scale" aria-label="Collapse Scale">&times;</button>
          </div>
          <div class="aero-scale-row aero-scale-mi">
            <span class="aero-scale-unit-label">mi</span>
            <div class="aero-scale-bar-wrapper">
              <div class="aero-scale-bar" id="aero-scale-bar-mi"></div>
            </div>
            <span class="aero-scale-val" id="aero-scale-val-mi">-- mi</span>
          </div>
          <div class="aero-scale-row aero-scale-nm">
            <span class="aero-scale-unit-label">NM</span>
            <div class="aero-scale-bar-wrapper">
              <div class="aero-scale-bar" id="aero-scale-bar-nm"></div>
            </div>
            <span class="aero-scale-val" id="aero-scale-val-nm">-- NM</span>
          </div>
          <div class="aero-scale-row aero-scale-km">
            <span class="aero-scale-unit-label">km</span>
            <div class="aero-scale-bar-wrapper">
              <div class="aero-scale-bar" id="aero-scale-bar-km"></div>
            </div>
            <span class="aero-scale-val" id="aero-scale-val-km">-- km</span>
          </div>
        </div>
      `;
      this._latInd = this._container.querySelector('#aero-scale-lat-ind');
      this._barMi = this._container.querySelector('#aero-scale-bar-mi');
      this._valMi = this._container.querySelector('#aero-scale-val-mi');
      this._barNm = this._container.querySelector('#aero-scale-bar-nm');
      this._valNm = this._container.querySelector('#aero-scale-val-nm');
      this._barKm = this._container.querySelector('#aero-scale-bar-km');
      this._valKm = this._container.querySelector('#aero-scale-val-km');

      const closeBtn = this._container.querySelector('#aero-scale-close-btn');
      if (closeBtn) {
        L.DomEvent.on(closeBtn, 'click', (e) => {
          L.DomEvent.preventDefault(e);
          L.DomEvent.stopPropagation(e);
          this.collapse();
        });
      }
    },

    _update: function () {
      if (!this._map) return;
      const center = this._map.getCenter();
      const lat = center.lat;
      const zoom = this._map.getZoom();
      const maxWidth = this.options.maxWidth || 110;

      // Ground resolution in meters per pixel with cos(lat) latitude correction
      const metersPerPixel = (40075016.68557849 * Math.cos(lat * Math.PI / 180)) / (256 * Math.pow(2, zoom));
      const maxMeters = maxWidth * metersPerPixel;

      if (isNaN(maxMeters) || maxMeters <= 0) return;

      if (this._latInd) {
        const dir = lat >= 0 ? 'N' : 'S';
        this._latInd.textContent = `${Math.abs(lat).toFixed(1)}°${dir}`;
      }

      this._updateUnitScale(maxMeters, 1609.344, 'mi', this._barMi, this._valMi, metersPerPixel, maxWidth);
      this._updateUnitScale(maxMeters, 1852.0, 'NM', this._barNm, this._valNm, metersPerPixel, maxWidth);
      this._updateUnitScale(maxMeters, 1000.0, 'km', this._barKm, this._valKm, metersPerPixel, maxWidth);
    },

    _updateUnitScale: function (maxMeters, metersPerUnit, unitLabel, barEl, valEl, metersPerPixel, maxWidth) {
      const maxUnits = maxMeters / metersPerUnit;
      const niceNum = getNiceScaleNumber(maxUnits);
      const targetMeters = niceNum * metersPerUnit;
      const widthPx = Math.max(1, Math.min(maxWidth, Math.round(targetMeters / metersPerPixel)));

      if (barEl) {
        barEl.style.width = widthPx + 'px';
      }
      if (valEl) {
        valEl.textContent = `${niceNum} ${unitLabel}`;
      }
    }
  });

  L.control.aeroScale = function (options) {
    return new AeroScaleControl(options);
  };

  // --- Map Initialization ---
  function initMap() {
    const commonTileOptions = {
      minZoom: 2,
      maxZoom: 20,
      maxNativeZoom: 19,
      keepBuffer: 8,
      updateWhenZooming: true,
      updateWhenIdle: false
    };

    const cartoMidnight = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=cb1_272f_1_6642cd2a2abfdf826cc7fc9c', {
      ...commonTileOptions,
      attribution: '&copy; CARTO &copy; OpenStreetMap'
    });

    const cartoDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=cb1_272f_1_6642cd2a2abfdf826cc7fc9c', {
      ...commonTileOptions,
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    });

    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      ...commonTileOptions,
      attribution: '&copy; OpenStreetMap contributors'
    });

    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      ...commonTileOptions,
      maxNativeZoom: 18,
      attribution: '&copy; Esri, Maxar, Earthstar Geographics'
    });

    map = L.map('map', {
      center: [STATE.circleCenter.lat, STATE.circleCenter.lng],
      zoom: 9,
      minZoom: 2,
      maxZoom: 20,
      layers: [cartoMidnight],
      zoomControl: false,
      preferCanvas: false,
      scrollWheelZoom: true,
      wheelPxPerZoomLevel: 60,
      wheelDebounceTime: 40,
      zoomSnap: 1,
      zoomDelta: 1.0,
      zoomAnimation: true,
      zoomAnimationThreshold: 8
    });

    function updateScaleButtonState(isExpanded) {
      if (scaleToggleBtn) {
        if (isExpanded) {
          scaleToggleBtn.classList.add('active');
          scaleToggleBtn.setAttribute('aria-expanded', 'true');
        } else {
          scaleToggleBtn.classList.remove('active');
          scaleToggleBtn.setAttribute('aria-expanded', 'false');
        }
      }
    }

    // Custom zoom control that performs animated zoom transitions for + / - buttons
    const customZoomControl = L.Control.extend({
      options: { position: 'topright' },
      onAdd: function (mapInstance) {
        const container = L.DomUtil.create('div', 'leaflet-control-zoom leaflet-bar leaflet-control');
        const zoomInBtn = L.DomUtil.create('a', 'leaflet-control-zoom-in', container);
        zoomInBtn.href = '#';
        zoomInBtn.title = 'Zoom in';
        zoomInBtn.role = 'button';
        zoomInBtn.ariaLabel = 'Zoom in';
        zoomInBtn.innerHTML = '<span aria-hidden="true">+</span>';

        const zoomOutBtn = L.DomUtil.create('a', 'leaflet-control-zoom-out', container);
        zoomOutBtn.href = '#';
        zoomOutBtn.title = 'Zoom out';
        zoomOutBtn.role = 'button';
        zoomOutBtn.ariaLabel = 'Zoom out';
        zoomOutBtn.innerHTML = '<span aria-hidden="true">&#x2212;</span>';

        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);

        L.DomEvent.on(zoomInBtn, 'click', function (e) {
          L.DomEvent.preventDefault(e);
          mapInstance.zoomIn(mapInstance.options.zoomDelta || 1, { animate: true });
        });

        L.DomEvent.on(zoomOutBtn, 'click', function (e) {
          L.DomEvent.preventDefault(e);
          mapInstance.zoomOut(mapInstance.options.zoomDelta || 1, { animate: true });
        });

        return container;
      }
    });

    new customZoomControl().addTo(map);

    // Tri-unit Map Scale Control in bottom-right (Statute Miles, Nautical Miles, Kilometers)
    aeroScaleControl = L.control.aeroScale({
      position: 'bottomright',
      maxWidth: 110
    }).addTo(map);

    const baseMaps = {
      "Aero Midnight (Dark)": cartoMidnight,
      "Aviation VFR (Light)": cartoDark,
      "OpenStreetMap": osm,
      "Satellite Imagery": satellite
    };

    L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

    // Scale Toggle Button under Map Layers Control
    const ScaleToggleControl = L.Control.extend({
      options: { position: 'topright' },
      onAdd: function () {
        const container = L.DomUtil.create('div', 'leaflet-control-scale-toggle leaflet-bar leaflet-control');
        const btn = L.DomUtil.create('a', 'leaflet-control-scale-btn', container);
        btn.href = '#';
        btn.title = 'Toggle Distance Scale (mi / NM / km)';
        btn.role = 'button';
        btn.ariaLabel = 'Toggle Distance Scale';
        btn.innerHTML = '<span class="scale-btn-icon" aria-hidden="true">📏</span>';
        scaleToggleBtn = btn;

        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);

        L.DomEvent.on(btn, 'click', function (e) {
          L.DomEvent.preventDefault(e);
          if (aeroScaleControl) {
            aeroScaleControl.toggle();
          }
        });

        return container;
      }
    });
    new ScaleToggleControl().addTo(map);

    if (window.innerWidth <= 860) {
      aeroScaleControl.collapse();
    } else {
      updateScaleButtonState(true);
    }

    // Markers layer
    markersLayerGroup = L.layerGroup().addTo(map);

    // Fuel Route layer
    routeLayerGroup = L.layerGroup().addTo(map);

    // Search Radius Circle
    const radiusMeters = getRadiusInMeters();
    radiusCircle = L.circle([STATE.circleCenter.lat, STATE.circleCenter.lng], {
      radius: radiusMeters,
      color: '#38bdf8',
      weight: 2,
      opacity: 0.85,
      dashArray: '6, 6',
      fillColor: '#0284c7',
      fillOpacity: 0.12,
      interactive: false
    }).addTo(map);

    // Center Crosshair Reticle Icon
    const reticleIcon = L.divIcon({
      className: 'center-reticle',
      html: `
        <div style="
          width: 24px; height: 24px;
          border: 2px solid #38bdf8;
          border-radius: 50%;
          position: relative;
          box-shadow: 0 0 12px rgba(56, 189, 248, 0.8);
          transform: translate(-50%, -50%);
          pointer-events: none;
        ">
          <div style="position: absolute; top: 50%; left: -6px; width: 36px; height: 2px; background: #38bdf8; transform: translateY(-50%);"></div>
          <div style="position: absolute; left: 50%; top: -6px; height: 36px; width: 2px; background: #38bdf8; transform: translateX(-50%);"></div>
          <div style="position: absolute; top: 50%; left: 50%; width: 6px; height: 6px; background: #fff; border-radius: 50%; transform: translate(-50%, -50%);"></div>
        </div>
      `,
      iconSize: [0, 0]
    });

    centerReticleMarker = L.marker([STATE.circleCenter.lat, STATE.circleCenter.lng], {
      icon: reticleIcon,
      interactive: false
    }).addTo(map);

    // Vector line connecting center to lowest price airport
    vectorLine = L.polyline([], {
      color: '#10b981',
      weight: 2.5,
      opacity: 0.9,
      dashArray: '5, 8',
      interactive: false
    }).addTo(map);

    // Navigational Vector line connecting center back towards Origin Airport
    originVectorLine = L.polyline([], {
      color: '#818cf8',
      weight: 2.5,
      opacity: 0.9,
      dashArray: '6, 6',
      interactive: false
    }).addTo(map);

    const vectorLabelIcon = L.divIcon({
      className: 'custom-vector-label-div-icon',
      html: '<div class="origin-vector-badge" style="display: none;"></div>',
      iconSize: [0, 0]
    });

    originVectorLabel = L.marker([STATE.circleCenter.lat, STATE.circleCenter.lng], {
      icon: vectorLabelIcon,
      interactive: false,
      zIndexOffset: 8500
    }).addTo(map);

    // Initialize fast canvas overlay for background airport dots
    initAirportCanvas();

    // Setup mouse movement, drag & click listeners
    setupMapListeners();

    updateOriginVectorLine();
  }

  function getRadiusInMeters() {
    const factor = UNIT_TO_METERS[STATE.radiusUnit] || 1609.344;
    return STATE.radiusValue * factor;
  }

  function getRadiusInMiles() {
    const factor = UNIT_TO_MILES[STATE.radiusUnit] || 1.0;
    return STATE.radiusValue * factor;
  }

  // --- Canvas Background Layer for Airport Dots (Zero DOM Bloat) ---
  let canvasBounds = null;

  function initAirportCanvas() {
    if (airportCanvasEl) return;
    airportCanvasEl = L.DomUtil.create('canvas', 'airport-dots-canvas leaflet-zoom-animated');
    airportCanvasEl.style.position = 'absolute';
    airportCanvasEl.style.pointerEvents = 'none'; // Clicks handled via map hit-testing
    airportCanvasEl.style.zIndex = '450';

    // Append to Leaflet's overlayPane so canvas is hardware-transformed with map tiles
    map.getPanes().overlayPane.appendChild(airportCanvasEl);
    airportCanvasCtx = airportCanvasEl.getContext('2d');

    const updateCanvasAndRedraw = () => {
      if (!map || !airportCanvasEl || !airportCanvasCtx) return;
      redrawAirportCanvas();
    };

    let moveRafPending = false;
    const scheduleRedraw = () => {
      if (moveRafPending) return;
      moveRafPending = true;
      requestAnimationFrame(() => {
        moveRafPending = false;
        redrawAirportCanvas();
      });
    };

    map.on('move', scheduleRedraw);
    map.on('drag', scheduleRedraw);

    // During zoom animation: perform zero CPU loops, only GPU CSS transform scaling!
    map.on('zoomanim', (e) => {
      if (!airportCanvasEl || !map || !canvasBounds || !e) return;
      const scale = map.getZoomScale(e.zoom, map.getZoom());
      const offset = map._latLngToNewLayerPoint(canvasBounds.getNorthWest(), e.zoom, e.center);
      L.DomUtil.setTransform(airportCanvasEl, offset, scale);
    });

    map.on('moveend', () => {
      if (radiusCircle && radiusCircle._renderer) {
        radiusCircle._renderer._update();
      }
      redrawAirportCanvas();
      recalculateRadiusAirports();
    });
    map.on('zoomend', () => {
      if (radiusCircle && radiusCircle._renderer) {
        radiusCircle._renderer._update();
      }
      redrawAirportCanvas();
      recalculateRadiusAirports();
    });
    map.on('resize', updateCanvasAndRedraw);
    map.on('viewreset', updateCanvasAndRedraw);

    updateCanvasAndRedraw();
  }

  function redrawAirportCanvas() {
    if (!airportCanvasCtx || !map || !STATE.airports || STATE.airports.length === 0) return;

    const size = map.getSize();
    const pixelRatio = window.devicePixelRatio || 1;
    const bounds = map.getBounds();
    canvasBounds = bounds;
    const topLeft = map.latLngToLayerPoint(bounds.getNorthWest());

    // Position canvas element exactly at current layer top-left point inside overlayPane
    L.DomUtil.setPosition(airportCanvasEl, topLeft);
    L.DomUtil.setTransform(airportCanvasEl, topLeft, 1);

    // Synchronize canvas buffer dimensions with map viewport
    const targetWidth = Math.round(size.x * pixelRatio);
    const targetHeight = Math.round(size.y * pixelRatio);
    if (airportCanvasEl.width !== targetWidth || airportCanvasEl.height !== targetHeight) {
      airportCanvasEl.width = targetWidth;
      airportCanvasEl.height = targetHeight;
      airportCanvasEl.style.width = size.x + 'px';
      airportCanvasEl.style.height = size.y + 'px';
    }

    airportCanvasCtx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    airportCanvasCtx.clearRect(0, 0, size.x, size.y);

    const padLat = (bounds.getNorth() - bounds.getSouth()) * 0.15;
    const padLon = (bounds.getEast() - bounds.getWest()) * 0.15;
    const minLat = bounds.getSouth() - padLat;
    const maxLat = bounds.getNorth() + padLat;
    const minLon = bounds.getWest() - padLon;
    const maxLon = bounds.getEast() + padLon;

    const zoom = map.getZoom();
    const dotRadius = Math.max(1.2, Math.min(4.5, 0.35 * zoom));

    const highlightedIcaos = STATE.activeHighlightedIcaos || new Set();

    for (let i = 0; i < STATE.airports.length; i++) {
      const apt = STATE.airports[i];
      if (apt.lat < minLat || apt.lat > maxLat || apt.lon < minLon || apt.lon > maxLon) {
        continue;
      }

      // Skip drawing dot if active interactive DOM marker is rendered on top
      if (highlightedIcaos.has(apt.icao)) {
        continue;
      }

      // Compute exact layer point and offset relative to canvas element top-left
      const layerPt = map.latLngToLayerPoint([apt.lat, apt.lon]);
      const x = layerPt.x - topLeft.x;
      const y = layerPt.y - topLeft.y;

      if (x < -10 || x > size.x + 10 || y < -10 || y > size.y + 10) {
        continue;
      }

      const fuelInfo = getEffectiveFuelInfo(apt);
      const isSearched = hasFetchedPrice(apt);

      if (!matchesPriceTier(fuelInfo, isSearched)) {
        continue;
      }

      if (fuelInfo) {
        const tier = getFuelTierInfo(fuelInfo.price);
        const color = tier.color;
        const alpha = tier.alpha;

        // Draw outer stroke ring / bright halo for airports with known fuel prices
        airportCanvasCtx.beginPath();
        airportCanvasCtx.arc(x, y, dotRadius + (zoom >= 8 ? 2.5 : 1.8), 0, Math.PI * 2);
        airportCanvasCtx.strokeStyle = color;
        airportCanvasCtx.lineWidth = 1.4;
        airportCanvasCtx.globalAlpha = 0.50;
        airportCanvasCtx.stroke();

        airportCanvasCtx.beginPath();
        airportCanvasCtx.arc(x, y, dotRadius, 0, Math.PI * 2);
        airportCanvasCtx.fillStyle = color;
        airportCanvasCtx.globalAlpha = alpha;
        airportCanvasCtx.fill();
      } else if (isSearched) {
        // Searched on AirNav but confirmed NO matching commercial fuel available:
        // Render with distinct muted charcoal-slate fill and an amber-red "no-fuel" ring indicator
        airportCanvasCtx.beginPath();
        airportCanvasCtx.arc(x, y, dotRadius + (zoom >= 8 ? 2.0 : 1.4), 0, Math.PI * 2);
        airportCanvasCtx.strokeStyle = '#f43f5e'; // Rose-red ring
        airportCanvasCtx.lineWidth = 1.2;
        airportCanvasCtx.globalAlpha = 0.70;
        airportCanvasCtx.stroke();

        airportCanvasCtx.beginPath();
        airportCanvasCtx.arc(x, y, Math.max(1.0, dotRadius - 0.4), 0, Math.PI * 2);
        airportCanvasCtx.fillStyle = '#475569'; // Dark slate center
        airportCanvasCtx.globalAlpha = 0.85;
        airportCanvasCtx.fill();
      } else {
        // Unsearched / Unfetched airport: subtle neutral slate dot
        airportCanvasCtx.beginPath();
        airportCanvasCtx.arc(x, y, dotRadius, 0, Math.PI * 2);
        airportCanvasCtx.fillStyle = '#64748b';
        airportCanvasCtx.globalAlpha = 0.45;
        airportCanvasCtx.fill();
      }
    }
    airportCanvasCtx.globalAlpha = 1.0;
  }

  /**
   * Spatial hit testing: finds closest airport to map click coordinates.
   * Performs oriented capsule/bounding box hit-testing in screen space:
   * 1. Dot distance: within 20px of coordinate center dot
   * 2. Badge bounding box: horizontal distance |dx| <= 65px, vertical distance -45px <= dy <= 15px
   */
  function findAirportNearPoint(latlng, maxPixelDist = 20) {
    if (!map || !latlng || latlng.lat === undefined || latlng.lng === undefined || !STATE.airports || STATE.airports.length === 0) return null;
    const clickPt = map.latLngToContainerPoint(latlng);
    let closestApt = null;
    let bestDist = Infinity;

    // Search candidates with zoom-adaptive geographic radius (converting ~85px screen distance to miles)
    let searchRadiusMiles = 40;
    try {
      const p1 = clickPt;
      const p2 = map.containerPointToLatLng([p1.x + 85, p1.y]);
      const p3 = map.containerPointToLatLng([p1.x, p1.y - 65]);
      const r1 = haversineMiles(latlng.lat, latlng.lng, p2.lat, p2.lng);
      const r2 = haversineMiles(latlng.lat, latlng.lng, p3.lat, p3.lng);
      searchRadiusMiles = Math.max(40, r1 * 1.5, r2 * 1.5);
    } catch (e) {
      searchRadiusMiles = 60;
    }

    const candidates = querySpatialCandidates(latlng.lat, latlng.lng, searchRadiusMiles);
    for (let i = 0; i < candidates.length; i++) {
      const apt = candidates[i];
      const pt = map.latLngToContainerPoint([apt.lat, apt.lon]);
      const dx = clickPt.x - pt.x;
      const dy = clickPt.y - pt.y;
      const dotDist = Math.sqrt(dx * dx + dy * dy);

      // Hit test 1: Within dot radius (default 20px)
      const isDotHit = dotDist <= Math.max(maxPixelDist, 20);

      // Hit test 2: Within bubble badge bounding area (horizontal |dx| <= 65px, vertical -45px <= dy <= 15px)
      const isBadgeHit = Math.abs(dx) <= 65 && dy >= -45 && dy <= 15;

      if (isDotHit || isBadgeHit) {
        // Distance to badge center (approx 18px above coordinate point) or dot
        const badgeCenterDist = Math.sqrt(dx * dx + (dy + 18) * (dy + 18));
        const effectiveDist = Math.min(dotDist, badgeCenterDist);
        if (effectiveDist < bestDist) {
          bestDist = effectiveDist;
          closestApt = apt;
        }
      }
    }
    return closestApt;
  }

  // --- Map Event Handlers ---
  function handlePopupButtonClick(e) {
    if (!e || !e.target) return;

    const btnDetails = e.target.closest('.btn-popup-open-details');
    if (btnDetails) {
      if (e.preventDefault) e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      const icao = btnDetails.getAttribute('data-icao');
      const cleanIcao = (icao || '').toUpperCase().trim();
      const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
      if (targetApt) {
        openAirportModal(targetApt, false);
      }
      return;
    }

    const btnRefresh = e.target.closest('.btn-popup-refresh');
    if (btnRefresh) {
      if (e.preventDefault) e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      const icao = btnRefresh.getAttribute('data-icao');
      const cleanIcao = (icao || '').toUpperCase().trim();
      const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
      if (targetApt) {
        fetchAirportFuelAndHighlight(targetApt, true);
      }
      return;
    }

    const btnOrigin = e.target.closest('.btn-popup-set-origin');
    if (btnOrigin) {
      if (e.preventDefault) e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      const icao = btnOrigin.getAttribute('data-icao');
      const cleanIcao = (icao || '').toUpperCase().trim();
      const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
      if (targetApt) {
        setOriginAirport(targetApt);
      }
      return;
    }
  }

  function isolatePopupEvents(popup) {
    if (!popup) return;
    const el = popup.getElement ? popup.getElement() : (popup._container || null);
    if (el) {
      if (!el._aerofuelEventsIsolated) {
        el._aerofuelEventsIsolated = true;
        L.DomEvent.disableClickPropagation(el);
        L.DomEvent.disableScrollPropagation(el);
        const stopProp = (e) => {
          if (e && e.stopPropagation) e.stopPropagation();
          if (e && e.originalEvent && e.originalEvent.stopPropagation) {
            e.originalEvent.stopPropagation();
          }
        };
        el.addEventListener('mousemove', stopProp);
        el.addEventListener('pointermove', stopProp);
        el.addEventListener('mouseenter', stopProp);
        el.addEventListener('mouseover', stopProp);
        el.addEventListener('pointerdown', stopProp);
        el.addEventListener('pointerup', stopProp);
        el.addEventListener('mousedown', stopProp);
        el.addEventListener('mouseup', stopProp);
      }
      if (!el._aerofuelButtonListenerAttached) {
        el._aerofuelButtonListenerAttached = true;
        el.addEventListener('click', handlePopupButtonClick);
      }
    }
  }

  function setupMapListeners() {
    const mapContainer = map.getContainer();

    // Listen for Leaflet popup lifecycle events for event isolation and state tracking
    map.on('popupopen', function (e) {
      if (e && e.popup) {
        isolatePopupEvents(e.popup);
        activeAirportPopup = e.popup;
      }
    });

    map.on('popupclose', function (e) {
      if (e && e.popup && (activeAirportPopup === e.popup || (STATE.activePopupIcao && (!activeAirportPopup || !activeAirportPopup.isOpen())))) {
        STATE.activePopupIcao = null;
        activeAirportPopup = null;
        recalculateRadiusAirports();
      }
    });

    // Track mouse move for 60 FPS circle repositioning or single airport tooltip hover
    mapContainer.addEventListener('mousemove', function (e) {
      if (STATE.radarEnabled && STATE.isLocked) return;
      const latlng = map.mouseEventToLatLng(e);
      if (latlng) {
        mousePendingPos = latlng;
        if (!animFrameId) {
          animFrameId = requestAnimationFrame(handleMouseMoveFrame);
        }
      }
    });

    mapContainer.addEventListener('mouseleave', function () {
      if (!STATE.radarEnabled) {
        clearRadarOffHoverMarker();
      }
    });

    // Smooth map panning & dragging without jumping to center
    map.on('move', function () {
      if (!STATE.isLocked && mousePendingPos && map) {
        updateOriginVectorLine();
      }
    });

    map.on('movestart zoomstart', function () {
      if (!STATE.radarEnabled) {
        clearRadarOffHoverMarker();
      }
    });

    // Click map to inspect clicked airport (or do nothing if empty map canvas is clicked)
    map.on('click', function (e) {
      // Spatial hit test for canvas airport dots & bubble badge offsets
      const clickedApt = findAirportNearPoint(e.latlng, 20);
      if (clickedApt) {
        fetchAirportFuelAndHighlight(clickedApt);
        return;
      }
      if (!STATE.radarEnabled && STATE.selectedAirport) {
        STATE.selectedAirport = null;
        updateBestDealHUD(null, []);
        recalculateRadiusAirports();
      }
    });

    // Keyboard shortcuts
    window.addEventListener('keydown', function (e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
        if (e.code === 'Escape') {
          e.target.blur();
          const dropdown = document.getElementById('search-dropdown');
          if (dropdown) dropdown.style.display = 'none';
        }
        return;
      }

      if (e.code === 'Escape') {
        if (activeAirportPopup && map) {
          map.closePopup(activeAirportPopup);
          activeAirportPopup = null;
          STATE.activePopupIcao = null;
        }
        closeModal();
        const dsModal = document.getElementById('data-source-modal-backdrop');
        if (dsModal) dsModal.classList.remove('open');
        return;
      }

      const modalOpen = document.querySelector('.modal-backdrop.open');
      if (!modalOpen && e.code === 'Space') {
        e.preventDefault();
        STATE.isLocked = !STATE.isLocked;
        updateUIControls();
        recalculateRadiusAirports();
        showToast(STATE.isLocked ? `📍 Radius Locked` : `🔓 Radius Following Mouse`);
      }

      if (!modalOpen && !e.ctrlKey && !e.metaKey && !e.altKey && (e.code === 'KeyR' || e.key === 'r' || e.key === 'R')) {
        e.preventDefault();
        setRadarEnabled(!STATE.radarEnabled);
      }
    });
  }

  let hoveredAirportIcao = null;

  function renderSingleHoverMarker(apt) {
    if (!apt) return;
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const originIcao = STATE.originAirport ? (STATE.originAirport.icao || '').toUpperCase().trim() : null;
    const originFaa = STATE.originAirport ? (STATE.originAirport.faa || '').toUpperCase().trim() : null;
    const isOrigin = Boolean(originIcao && (cleanIcao === originIcao || (cleanFaa && cleanFaa === originFaa)));
    const activePopupIcao = STATE.activePopupIcao ? STATE.activePopupIcao.toUpperCase().trim() : null;
    const isPopupOpen = Boolean(activePopupIcao && (cleanIcao === activePopupIcao || (cleanFaa && cleanFaa === activePopupIcao)));

    const isFetched = hasFetchedPrice(apt);
    const fuelInfo = isFetched ? getEffectiveFuelInfo(apt) : null;
    const tierClass = getMarkerTierClass(apt, fuelInfo, isFetched);
    const hasPriceClass = fuelInfo ? 'has-fuel-price' : 'no-fuel-price';
    const badgeInnerHtml = getBadgeHtml(apt, fuelInfo, isFetched);
    const routeInfo = getRouteStopInfo(apt);
    const isRouteWaypoint = Boolean(routeInfo);
    const originClass = (isOrigin && !isRouteWaypoint) ? 'is-origin' : '';
    const routeClass = isRouteWaypoint ? 'is-route-waypoint' : '';
    const zOffset = isPopupOpen ? 11500 : (isRouteWaypoint ? 11000 : (isOrigin ? 9000 : 1200));

    let markerObj = STATE.markers.get(apt.icao);

    if (!markerObj) {
      const iconHtml = `
        <div class="airport-marker-container ${tierClass} ${hasPriceClass} in-radius ${originClass} ${routeClass} is-hover-bubble" id="marker-${apt.icao}" title="${apt.icao} - ${apt.name} (${apt.city}, ${apt.state})">
          <div class="origin-ribbon" style="${isOrigin && !isRouteWaypoint ? 'display: flex;' : 'display: none;'}">🛫 ORIGIN</div>
          <div class="origin-pulse-ring" style="${isOrigin ? 'display: block;' : 'display: none;'}"></div>
          <div class="route-ribbon" style="${isRouteWaypoint ? 'display: flex;' : 'display: none;'}">${routeInfo ? routeInfo.label : ''}</div>
          <div class="lowest-ribbon" style="display: none;">🏆 LOWEST</div>
          <div class="pulse-ring" style="display: none;"></div>
          <div class="fuel-price-badge ${hasPriceClass} ${tierClass}">
            ${badgeInnerHtml}
          </div>
          <div class="marker-dot"></div>
        </div>
      `;

      const markerIcon = L.divIcon({
        className: 'custom-airport-div-icon',
        html: iconHtml,
        iconSize: [0, 0]
      });

      const marker = L.marker([apt.lat, apt.lon], { icon: markerIcon });
      marker.on('click', function (e) {
        if (e) {
          L.DomEvent.stopPropagation(e);
          if (e.originalEvent) {
            L.DomEvent.stopPropagation(e.originalEvent);
          }
        }
        fetchAirportFuelAndHighlight(apt);
      });
      marker.on('add', function () {
        attachMarkerDomListeners(apt.icao, apt);
      });

      marker.addTo(markersLayerGroup);
      markerObj = { marker, apt, tierClass, fuelInfo };
      STATE.markers.set(apt.icao, markerObj);
      marker.setZIndexOffset(zOffset);
      attachMarkerDomListeners(apt.icao, apt);
    } else {
      markerObj.marker.setZIndexOffset(zOffset);
      const el = document.getElementById(`marker-${apt.icao}`);
      if (el) {
        el.classList.add('in-radius', 'is-hover-bubble');
        updateMarkerBadgeContent(apt);
        attachMarkerDomListeners(apt.icao, apt, el);
      }
    }
  }

  function clearRadarOffHoverMarker() {
    if (!hoveredAirportIcao) return;
    const prevIcao = hoveredAirportIcao;
    hoveredAirportIcao = null;

    const cleanPrev = prevIcao.toUpperCase().trim();
    const originIcao = STATE.originAirport ? (STATE.originAirport.icao || '').toUpperCase().trim() : null;
    const originFaa = STATE.originAirport ? (STATE.originAirport.faa || '').toUpperCase().trim() : null;
    const isOrigin = Boolean(originIcao && (cleanPrev === originIcao || (originFaa && cleanPrev === originFaa)));
    const destIcao = STATE.destinationAirport ? (STATE.destinationAirport.icao || '').toUpperCase().trim() : null;
    const destFaa = STATE.destinationAirport ? (STATE.destinationAirport.faa || '').toUpperCase().trim() : null;
    const isDest = Boolean(destIcao && (cleanPrev === destIcao || (destFaa && cleanPrev === destFaa)));
    const activePopupIcao = STATE.activePopupIcao ? STATE.activePopupIcao.toUpperCase().trim() : null;
    const isPopupOpen = Boolean(activePopupIcao && (cleanPrev === activePopupIcao || (originFaa && cleanPrev === activePopupIcao)));
    const aptCanonical = STATE.airportsMap.get(cleanPrev) || (cleanPrev.startsWith('K') ? STATE.airportsMap.get(cleanPrev.slice(1)) : STATE.airportsMap.get('K' + cleanPrev)) || { icao: cleanPrev, faa: cleanPrev };
    const isRouteWaypoint = Boolean(getRouteStopInfo(aptCanonical));

    if (!isOrigin && !isDest && !isPopupOpen && !isRouteWaypoint) {
      const markerObj = STATE.markers.get(prevIcao);
      if (markerObj && markerObj.marker) {
        markersLayerGroup.removeLayer(markerObj.marker);
      }
      STATE.markers.delete(prevIcao);
    } else {
      const el = document.getElementById(`marker-${prevIcao}`);
      if (el) {
        el.classList.remove('is-hover-bubble');
      }
    }
  }

  function handleRadarOffHover(latlng) {
    if (!latlng) {
      clearRadarOffHoverMarker();
      return;
    }

    const hoveredApt = findAirportNearPoint(latlng, 20);
    if (!hoveredApt) {
      clearRadarOffHoverMarker();
      return;
    }

    const cleanIcao = (hoveredApt.icao || '').toUpperCase().trim();
    if (hoveredAirportIcao && hoveredAirportIcao.toUpperCase().trim() === cleanIcao) {
      return; // Already hovering on this airport
    }

    // Switched to another airport
    clearRadarOffHoverMarker();
    hoveredAirportIcao = hoveredApt.icao;
    renderSingleHoverMarker(hoveredApt);
  }

  let sidebarAutoCollapsedForRadar = false;

  function setRadarSidebarCollapsed(collapsed) {
    const sidebar = document.getElementById('radar-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle-btn');
    if (!sidebar) return;

    if (collapsed) {
      sidebar.classList.add('minimized', 'collapsed');
      sidebar.classList.remove('open');
      document.body.classList.add('sidebar-minimized', 'sidebar-collapsed');
      if (sidebarToggle) {
        sidebarToggle.innerText = '▲';
        sidebarToggle.setAttribute('title', 'Expand Radar Sidebar');
      }
    } else {
      sidebar.classList.remove('minimized', 'collapsed');
      document.body.classList.remove('sidebar-minimized', 'sidebar-collapsed');
      if (sidebarToggle) {
        sidebarToggle.innerText = '▼';
        sidebarToggle.setAttribute('title', 'Minimize Radar Sidebar');
      }
    }
  }

  function setRadarEnabled(enabled, options = {}) {
    const silent = Boolean(options.silent);
    STATE.radarEnabled = Boolean(enabled);
    clearRadarOffHoverMarker();

    if (STATE.radarEnabled) {
      STATE.selectedAirport = null;
      if (radiusCircle) {
        radiusCircle.setStyle({ opacity: 0.85, fillOpacity: 0.12 });
      }
      if (centerReticleMarker) {
        centerReticleMarker.setOpacity(1);
      }
      updateOriginVectorLine();
      recalculateRadiusAirports();
      if (sidebarAutoCollapsedForRadar) {
        setRadarSidebarCollapsed(false);
        sidebarAutoCollapsedForRadar = false;
      }
      if (!silent) {
        showToast('📡 Search Radar Enabled');
      }
    } else {
      if (radiusCircle) {
        radiusCircle.setStyle({ opacity: 0, fillOpacity: 0 });
      }
      if (centerReticleMarker) {
        centerReticleMarker.setOpacity(0);
      }
      if (vectorLine) {
        vectorLine.setLatLngs([]);
      }
      updateOriginVectorLine();
      STATE.airportsInRadius = [];
      STATE.lowestAirport = null;
      STATE.prevInRadiusIcaos = new Set();
      STATE.prevLowestIcao = null;

      recalculateRadiusAirports();
      redrawAirportCanvas();
      if (STATE.selectedAirport) {
        showSelectedAirportHUD(STATE.selectedAirport);
      } else {
        updateBestDealHUD(null, []);
      }
      updateSidebarRadarList([], null);

      const sidebar = document.getElementById('radar-sidebar');
      const isMinimized = sidebar && (sidebar.classList.contains('minimized') || sidebar.classList.contains('collapsed'));
      if (!isMinimized) {
        sidebarAutoCollapsedForRadar = true;
      }
      setRadarSidebarCollapsed(true);

      if (!silent) {
        showToast('⚪ Search Radar Disabled');
      }
    }

    updateUIControls();
  }

  function handleMouseMoveFrame() {
    animFrameId = null;
    if (!mousePendingPos) return;

    if (STATE.radarEnabled) {
      if (STATE.isLocked) return;
      STATE.circleCenter = { lat: mousePendingPos.lat, lng: mousePendingPos.lng };
      updateCirclePosition(STATE.circleCenter.lat, STATE.circleCenter.lng);
      recalculateRadiusAirports();
    } else {
      handleRadarOffHover(mousePendingPos);
    }
  }

  function updateCirclePosition(lat, lng) {
    if (radiusCircle) {
      radiusCircle.setLatLng([lat, lng]);
    }
    if (centerReticleMarker) {
      centerReticleMarker.setLatLng([lat, lng]);
    }
    updateOriginVectorLine();
  }

  function updateOriginVectorLine() {
    if (!originVectorLine) return;

    if (!STATE.originAirport || !STATE.radarEnabled) {
      originVectorLine.setLatLngs([]);
      if (originVectorLabel) {
        originVectorLabel.setOpacity(0);
        originVectorLabel.setLatLng([0, 0]);
        const el = originVectorLabel.getElement ? originVectorLabel.getElement() : null;
        if (el) el.style.display = 'none';
      }
      const readoutEl = document.getElementById('origin-vector-readout');
      if (readoutEl) readoutEl.style.display = 'none';
      return;
    }

    const originLat = STATE.originAirport.lat;
    const originLon = STATE.originAirport.lon;
    const centerLat = STATE.circleCenter.lat;
    const centerLon = STATE.circleCenter.lng;

    const originDistMiles = haversineMiles(centerLat, centerLon, originLat, originLon);
    const originIdent = STATE.originAirport.faa || STATE.originAirport.icao;

    // --- Determine the target endpoint ---
    // When a route is active, connect to the nearest stop on the route instead of the origin airport
    let targetLat = originLat;
    let targetLon = originLon;
    let targetIdent = originIdent;
    let targetLabel = `TO ${originIdent}`;

    if (STATE.activeRoute && STATE.activeRoute.stops && STATE.activeRoute.stops.length > 0) {
      let nearestStop = null;
      let nearestDist = Infinity;
      for (const stop of STATE.activeRoute.stops) {
        let sLat = stop.lat;
        let sLon = stop.lon;
        // Resolve coords from local airport map if missing
        if (sLat === null || sLon === null || sLat === undefined || sLon === undefined) {
          const apt = STATE.airportsMap.get(stop.airport_code) || STATE.airportsMap.get('K' + stop.airport_code);
          if (apt) { sLat = apt.lat; sLon = apt.lon; }
        }
        if (sLat === null || sLon === null || isNaN(sLat) || isNaN(sLon)) continue;
        const d = haversineMiles(centerLat, centerLon, sLat, sLon);
        if (d < nearestDist) {
          nearestDist = d;
          nearestStop = { lat: sLat, lon: sLon, code: stop.airport_code };
        }
      }
      if (nearestStop) {
        targetLat = nearestStop.lat;
        targetLon = nearestStop.lon;
        targetIdent = nearestStop.code;
        targetLabel = `TO ${nearestStop.code} (route)`;
      }
    }

    const distMiles = haversineMiles(centerLat, centerLon, targetLat, targetLon);
    const distFormatted = formatDistance(distMiles);

    // Gracefully hide the vector line & label when circle center is directly centered on target (< 0.8 mi)
    if (distMiles < 0.8) {
      originVectorLine.setLatLngs([]);
      if (originVectorLabel) {
        originVectorLabel.setOpacity(0);
        originVectorLabel.setLatLng([0, 0]);
        const el = originVectorLabel.getElement ? originVectorLabel.getElement() : null;
        if (el) el.style.display = 'none';
      }
      const readoutEl = document.getElementById('origin-vector-readout');
      if (readoutEl) {
        readoutEl.style.display = 'flex';
        readoutEl.innerHTML = `<span class="readout-centered">🎯 Centered on ${targetIdent}</span>`;
      }
      return;
    }

    // Connect mouse circle center to the target (origin or nearest route stop)
    originVectorLine.setLatLngs([
      [centerLat, centerLon],
      [targetLat, targetLon]
    ]);
    originVectorLine.setStyle({ opacity: 0.9 });

    const bearing = calculateBearing(centerLat, centerLon, targetLat, targetLon);
    const direction = getCompassDirection(bearing);
    const bearingStr = bearing.toString().padStart(3, '0') + '°';

    // Midpoint position for floating navigational course label
    const midLat = (centerLat + targetLat) / 2;
    const midLon = (centerLon + targetLon) / 2;

    if (originVectorLabel) {
      originVectorLabel.setLatLng([midLat, midLon]);
      originVectorLabel.setOpacity(1);
      const badgeHtml = `
        <div class="origin-vector-badge">
          <span class="vector-bearing">🧭 ${bearingStr} ${direction}</span>
          <span class="vector-sep">•</span>
          <span class="vector-dist">${distFormatted}</span>
          <span class="vector-sep">•</span>
          <span class="vector-target">${targetLabel}</span>
        </div>
      `;
      const el = originVectorLabel.getElement ? originVectorLabel.getElement() : null;
      if (el) {
        el.style.display = 'block';
        el.innerHTML = badgeHtml;
      } else {
        originVectorLabel.setIcon(L.divIcon({
          className: 'custom-vector-label-div-icon',
          html: badgeHtml,
          iconSize: [0, 0]
        }));
      }
    }

    // Dynamic bearing & distance readout inside origin HUD container
    const readoutEl = document.getElementById('origin-vector-readout');
    if (readoutEl) {
      readoutEl.style.display = 'flex';
      readoutEl.innerHTML = `
        <span class="readout-label">🧭 Course to ${STATE.activeRoute ? 'Nearest Stop' : 'Origin'}:</span>
        <span class="readout-val"><strong>${bearingStr} ${direction}</strong> • ${distFormatted}</span>
      `;
    }
  }


  // --- Airport Markers Rendering ---
  function renderAllAirportMarkers() {
    const savedPopupIcao = STATE.activePopupIcao;
    markersLayerGroup.clearLayers();
    STATE.markers.clear();
    STATE.activeHighlightedIcaos = new Set();
    STATE.prevLowestIcao = null;
    STATE.prevInRadiusIcaos = new Set();
    STATE.prevSidebarSignature = '';
    STATE.prevBestDealSignature = '';

    updatePricePercentiles();

    initAirportCanvas();
    redrawAirportCanvas();

    if (savedPopupIcao) {
      STATE.activePopupIcao = savedPopupIcao;
    }

    // Recalculate radius selection
    recalculateRadiusAirports();

    if (savedPopupIcao) {
      const cleanIcao = savedPopupIcao.toUpperCase().trim();
      const popupApt = STATE.airportsMap.get(cleanIcao) || (cleanIcao.startsWith('K') ? STATE.airportsMap.get(cleanIcao.slice(1)) : STATE.airportsMap.get('K' + cleanIcao)) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
      if (popupApt) {
        openAirportPopup(popupApt, false);
      }
    }
  }

  function calculatePercentile(sortedArr, q) {
    if (!sortedArr || sortedArr.length === 0) return 0;
    if (sortedArr.length === 1) return sortedArr[0];
    const pos = q * (sortedArr.length - 1);
    const base = Math.floor(pos);
    const rest = pos - base;
    if (base + 1 < sortedArr.length) {
      return sortedArr[base] + rest * (sortedArr[base + 1] - sortedArr[base]);
    }
    return sortedArr[base];
  }

  function updatePricePercentiles() {
    // Compute price quintiles across fetched dataset for 5-tier color scale (p20, p40, p60, p80)
    const allPrices = [];
    for (let i = 0; i < STATE.airports.length; i++) {
      const fuelInfo = getEffectiveFuelInfo(STATE.airports[i]);
      if (fuelInfo && typeof fuelInfo.price === 'number' && !isNaN(fuelInfo.price)) {
        allPrices.push(fuelInfo.price);
      }
    }
    allPrices.sort((a, b) => a - b);
    STATE.cachedPriceValues = allPrices;

    if (allPrices.length >= 2) {
      STATE.p20 = calculatePercentile(allPrices, 0.20);
      STATE.p40 = calculatePercentile(allPrices, 0.40);
      STATE.p60 = calculatePercentile(allPrices, 0.60);
      STATE.p80 = calculatePercentile(allPrices, 0.80);
      STATE.p25 = calculatePercentile(allPrices, 0.25);
      STATE.p75 = calculatePercentile(allPrices, 0.75);
    } else if (allPrices.length === 1) {
      const val = allPrices[0];
      STATE.p20 = val;
      STATE.p40 = val;
      STATE.p60 = val;
      STATE.p80 = val;
      STATE.p25 = val;
      STATE.p75 = val;
    } else {
      STATE.p20 = 5.20;
      STATE.p40 = 5.80;
      STATE.p60 = 6.40;
      STATE.p80 = 7.00;
      STATE.p25 = 5.20;
      STATE.p75 = 6.50;
    }

    updateLegendUI();
  }

  // --- Fast Radius Calculation, Decluttering & Lowest Price Detection ---
  function recalculateRadiusAirports() {
    const inRadiusList = [];
    let lowest = null;
    let minPrice = Infinity;
    const centerLat = STATE.circleCenter.lat;
    const centerLon = STATE.circleCenter.lng;

    if (!STATE.radarEnabled) {
      STATE.airportsInRadius = [];
      STATE.lowestAirport = null;
      if (vectorLine) vectorLine.setLatLngs([]);
      updateOriginVectorLine();
      if (STATE.selectedAirport) {
        showSelectedAirportHUD(STATE.selectedAirport);
      } else {
        updateBestDealHUD(null, []);
      }
      updateSidebarRadarList([], null);
      // NOTE: Do not return early. Persistent markers (Origin, Destination, and active Route Stops), and selected airport
      // will still be accepted and rendered below even with radar disabled.
    } else {
      const radiusMilesLimit = getRadiusInMiles();

      // Fast candidate filtering via spatial grid index (< 0.05 ms)
      const candidates = querySpatialCandidates(centerLat, centerLon, radiusMilesLimit);

      for (let i = 0; i < candidates.length; i++) {
        const apt = candidates[i];
        const distMiles = haversineMiles(centerLat, centerLon, apt.lat, apt.lon);

        if (distMiles <= radiusMilesLimit) {
          const isFetched = hasFetchedPrice(apt);
          const fuelInfo = isFetched ? getEffectiveFuelInfo(apt) : null;
          if (!matchesPriceTier(fuelInfo, isFetched)) {
            continue;
          }
          const bearing = calculateBearing(centerLat, centerLon, apt.lat, apt.lon);
          const aptWithDist = {
            ...apt,
            distanceMiles: distMiles,
            bearing: bearing,
            direction: getCompassDirection(bearing),
            effectiveFuel: fuelInfo,
            hasFuel: fuelInfo !== null,
            isFetched: isFetched
          };

          inRadiusList.push(aptWithDist);

          // ONLY evaluate fetched priced airports for lowest price candidate
          if (fuelInfo) {
            if (fuelInfo.price < minPrice || (fuelInfo.price === minPrice && distMiles < (lowest ? lowest.distanceMiles : Infinity))) {
              minPrice = fuelInfo.price;
              lowest = aptWithDist;
            }
          }
        }
      }

      // Sort in-radius list: fetched priced airports first (by price, then distance), unfetched/unpriced airports last (by distance)
      inRadiusList.sort((a, b) => {
        if (a.hasFuel && b.hasFuel) {
          if (a.effectiveFuel.price !== b.effectiveFuel.price) {
            return a.effectiveFuel.price - b.effectiveFuel.price;
          }
          return a.distanceMiles - b.distanceMiles;
        }
        if (a.hasFuel && !b.hasFuel) return -1;
        if (!a.hasFuel && b.hasFuel) return 1;
        return a.distanceMiles - b.distanceMiles;
      });

      STATE.airportsInRadius = inRadiusList;
      STATE.lowestAirport = lowest;
    }

    // --- Smart Decluttering & Zoom/Radius Filtering ---
    // Dynamically cap highlighted DOM badges to eliminate screen clutter and DOM overhead
    const zoom = map ? map.getZoom() : 9;
    let tagBudget = 50;
    let minSeparationPx = 30;

    if (zoom <= 5) {
      tagBudget = 12;
      minSeparationPx = 38;
    } else if (zoom <= 7) {
      tagBudget = 22;
      minSeparationPx = 34;
    } else if (zoom <= 9) {
      tagBudget = 38;
      minSeparationPx = 28;
    } else {
      tagBudget = 65;
      minSeparationPx = 20;
    }

    const acceptedHighlightList = [];
    const acceptedScreenPoints = [];

    // #0 Priority: Origin Airport is ALWAYS accepted and rendered (Persistent Origin Marker)
    let originAptCanonical = null;
    const originIcao = STATE.originAirport ? (STATE.originAirport.icao || '').toUpperCase().trim() : null;
    const originFaa = STATE.originAirport ? (STATE.originAirport.faa || '').toUpperCase().trim() : null;

    if (STATE.originAirport && map) {
      originAptCanonical = STATE.airportsMap.get(originIcao) || (originFaa ? STATE.airportsMap.get(originFaa) : null) || STATE.originAirport;
      if (originAptCanonical) {
        const ptOrigin = map.latLngToContainerPoint([originAptCanonical.lat, originAptCanonical.lon]);
        acceptedHighlightList.push(originAptCanonical);
        acceptedScreenPoints.push(ptOrigin);
      }
    }

    // #0.1 Priority: Destination Airport is ALWAYS accepted and rendered
    let destAptCanonical = null;
    const destIcao = STATE.destinationAirport ? (STATE.destinationAirport.icao || '').toUpperCase().trim() : null;
    const destFaa = STATE.destinationAirport ? (STATE.destinationAirport.faa || '').toUpperCase().trim() : null;

    if (STATE.destinationAirport && map) {
      destAptCanonical = STATE.airportsMap.get(destIcao) || (destFaa ? STATE.airportsMap.get(destFaa) : null) || STATE.destinationAirport;
      if (destAptCanonical) {
        if (!acceptedHighlightList.some(a => (a.icao && a.icao.toUpperCase().trim() === destIcao) || (a.faa && a.faa.toUpperCase().trim() === destFaa))) {
          const ptDest = map.latLngToContainerPoint([destAptCanonical.lat, destAptCanonical.lon]);
          acceptedHighlightList.push(destAptCanonical);
          acceptedScreenPoints.push(ptDest);
        }
      }
    }

    // #0.2 Priority: Active Route Stops are ALWAYS accepted and rendered
    if (STATE.activeRoute && STATE.activeRoute.stops && map) {
      for (const stop of STATE.activeRoute.stops) {
        const stopCode = (stop.airport_code || '').toUpperCase().trim();
        let apt = STATE.airportsMap.get(stopCode) || (stopCode.startsWith('K') ? STATE.airportsMap.get(stopCode.slice(1)) : STATE.airportsMap.get('K' + stopCode));
        if (!apt && stop.lat !== undefined && stop.lon !== undefined && !isNaN(stop.lat) && !isNaN(stop.lon)) {
          apt = {
            icao: stopCode,
            faa: stopCode,
            name: stop.airport_name || `${stopCode} Airport`,
            city: stop.location ? stop.location.split(',')[0].trim() : '',
            state: stop.location && stop.location.includes(',') ? stop.location.split(',')[1].trim() : '',
            lat: Number(stop.lat),
            lon: Number(stop.lon),
            best_price: stop.price_num,
            primary_fuel: '100LL'
          };
        }
        if (apt && apt.lat !== undefined && apt.lon !== undefined && !isNaN(apt.lat) && !isNaN(apt.lon)) {
          if (!acceptedHighlightList.some(a => (a.icao && a.icao.toUpperCase().trim() === stopCode) || (a.faa && a.faa.toUpperCase().trim() === stopCode))) {
            const ptRoute = map.latLngToContainerPoint([apt.lat, apt.lon]);
            acceptedHighlightList.push(apt);
            acceptedScreenPoints.push(ptRoute);
          }
        }
      }
    }

    // #0.5 Priority: Active Open Popup Airport is ALWAYS accepted and rendered (Pin Open Popup Marker)
    let popupAptCanonical = null;
    const activePopupIcao = STATE.activePopupIcao ? STATE.activePopupIcao.toUpperCase().trim() : null;
    if (activePopupIcao && map) {
      popupAptCanonical = STATE.airportsMap.get(activePopupIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === activePopupIcao) || (a.faa && a.faa.toUpperCase().trim() === activePopupIcao));
      if (popupAptCanonical) {
        if (!acceptedHighlightList.some(a => (a.icao && a.icao.toUpperCase().trim() === activePopupIcao) || (a.faa && a.faa.toUpperCase().trim() === activePopupIcao))) {
          const ptPopup = map.latLngToContainerPoint([popupAptCanonical.lat, popupAptCanonical.lon]);
          acceptedHighlightList.push(popupAptCanonical);
          acceptedScreenPoints.push(ptPopup);
        }
      }
    // #0.6 Priority: Explicitly Selected Airport is ALWAYS accepted and rendered (Pin Selected Airport Marker)
    if (STATE.selectedAirport && map) {
      const selIcao = (STATE.selectedAirport.icao || STATE.selectedAirport.faa || '').toUpperCase().trim();
      const selApt = STATE.airportsMap.get(selIcao) || STATE.selectedAirport;
      if (selApt && !acceptedHighlightList.some(a => (a.icao && a.icao.toUpperCase().trim() === selIcao) || (a.faa && a.faa.toUpperCase().trim() === selIcao))) {
        const ptSel = map.latLngToContainerPoint([selApt.lat, selApt.lon]);
        acceptedHighlightList.push(selApt);
        acceptedScreenPoints.push(ptSel);
      }
    }

    // #1 Priority: Lowest price airport in radius is ALWAYS accepted and rendered (only when radar enabled)
    if (STATE.radarEnabled && lowest && map) {
      if (!acceptedHighlightList.some(a => a.icao === lowest.icao)) {
        const ptLowest = map.latLngToContainerPoint([lowest.lat, lowest.lon]);
        acceptedHighlightList.push(lowest);
        acceptedScreenPoints.push(ptLowest);
      }
    }

    // #2 Priority: Remaining in-radius candidates with fetched fuel prices (only when radar enabled)
    if (STATE.radarEnabled && map) {
      for (let i = 0; i < inRadiusList.length; i++) {
        const candidate = inRadiusList[i];
        if (!candidate.hasFuel || !candidate.effectiveFuel) continue;
        if (acceptedHighlightList.some(a => a.icao === candidate.icao)) continue;
        if (acceptedHighlightList.length >= tagBudget) break;

        const pt = map.latLngToContainerPoint([candidate.lat, candidate.lon]);
        let collides = false;

        for (let j = 0; j < acceptedScreenPoints.length; j++) {
          const existingPt = acceptedScreenPoints[j];
          const dx = pt.x - existingPt.x;
          const dy = pt.y - existingPt.y;
          const distSq = dx * dx + dy * dy;
          if (distSq < minSeparationPx * minSeparationPx) {
            collides = true;
            break;
          }
        }

        if (!collides) {
          acceptedHighlightList.push(candidate);
          acceptedScreenPoints.push(pt);
        }
      }
    }

    // #3 Priority: In-radius identifier-only airports (default unfetched presentation, only when radar enabled)
    if (STATE.radarEnabled && map) {
      for (let i = 0; i < inRadiusList.length; i++) {
        const candidate = inRadiusList[i];
        if (candidate.hasFuel && candidate.effectiveFuel) continue; // Already added above
        if (acceptedHighlightList.some(a => a.icao === candidate.icao)) continue;
        if (acceptedHighlightList.length >= tagBudget) break;

        const pt = map.latLngToContainerPoint([candidate.lat, candidate.lon]);
        let collides = false;

        for (let j = 0; j < acceptedScreenPoints.length; j++) {
          const existingPt = acceptedScreenPoints[j];
          const dx = pt.x - existingPt.x;
          const dy = pt.y - existingPt.y;
          const distSq = dx * dx + dy * dy;
          if (distSq < minSeparationPx * minSeparationPx) {
            collides = true;
            break;
          }
        }

        if (!collides) {
          acceptedHighlightList.push(candidate);
          acceptedScreenPoints.push(pt);
        }
      }
    }

    const currentHighlightedIcaos = new Set(acceptedHighlightList.map(a => (a.icao || '').toUpperCase().trim()));
    acceptedHighlightList.forEach(a => {
      if (a.faa) currentHighlightedIcaos.add(a.faa.toUpperCase().trim());
      if (a.icao && a.icao.startsWith('K')) currentHighlightedIcaos.add(a.icao.slice(1).toUpperCase().trim());
      else if (a.icao) currentHighlightedIcaos.add(('K' + a.icao).toUpperCase().trim());
    });
    if (destIcao) {
      currentHighlightedIcaos.add(destIcao);
      if (destFaa) currentHighlightedIcaos.add(destFaa);
      if (destIcao.startsWith('K')) currentHighlightedIcaos.add(destIcao.slice(1));
    }
    if (activePopupIcao) {
      currentHighlightedIcaos.add(activePopupIcao);
    }
    if (STATE.activeRoute && STATE.activeRoute.stops) {
      for (const stop of STATE.activeRoute.stops) {
        const stopCode = (stop.airport_code || '').toUpperCase().trim();
        currentHighlightedIcaos.add(stopCode);
        if (stopCode.startsWith('K')) currentHighlightedIcaos.add(stopCode.slice(1));
        else currentHighlightedIcaos.add('K' + stopCode);
      }
    }
    const currentInRadiusIcaos = new Set(inRadiusList.map(a => a.icao));

    // Remove DOM markers for airports no longer in the active highlighted subset (NEVER remove active popup, destination, or route markers)
    for (const [icao, markerObj] of STATE.markers.entries()) {
      const cleanKey = (icao || '').toUpperCase().trim();
      if (activePopupIcao) {
        if (cleanKey === activePopupIcao) continue;
        if (popupAptCanonical && ((popupAptCanonical.icao && popupAptCanonical.icao.toUpperCase().trim() === cleanKey) || (popupAptCanonical.faa && popupAptCanonical.faa.toUpperCase().trim() === cleanKey))) {
          continue;
        }
      }
      if (!currentHighlightedIcaos.has(cleanKey)) {
        if (markerObj && markerObj.marker) {
          markerObj.marker.setZIndexOffset(0);
          markersLayerGroup.removeLayer(markerObj.marker);
        }
        STATE.markers.delete(icao);
      }
    }

    // Instantiate or update DOM markers for accepted highlighted airports
    const p25 = STATE.p25 || 5.20;
    const p75 = STATE.p75 || 6.50;

    for (let i = 0; i < acceptedHighlightList.length; i++) {
      const candidateApt = acceptedHighlightList[i];
      const cleanIcao = (candidateApt.icao || '').toUpperCase().trim();
      const cleanFaa = (candidateApt.faa || '').toUpperCase().trim();
      const apt = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || candidateApt;
      const isFetched = hasFetchedPrice(apt);
      const fuelInfo = isFetched ? getEffectiveFuelInfo(apt) : null;
      const tierClass = getMarkerTierClass(apt, fuelInfo, isFetched);
      const hasPriceClass = fuelInfo ? 'has-fuel-price' : 'no-fuel-price';
      const badgeInnerHtml = getBadgeHtml(apt, fuelInfo, isFetched);
      const isInRadius = currentInRadiusIcaos.has(apt.icao);
      const routeInfo = getRouteStopInfo(apt);
      const isRouteWaypoint = Boolean(routeInfo);
      const isOrigin = Boolean(originIcao && (cleanIcao === originIcao || (cleanFaa && cleanFaa === originFaa)));
      const isDest = Boolean(destIcao && (cleanIcao === destIcao || (cleanFaa && cleanFaa === destFaa)));
      const isLowest = lowest && (apt.icao === lowest.icao || cleanIcao === lowest.icao);
      const isPopupOpen = Boolean(activePopupIcao && (cleanIcao === activePopupIcao || (cleanFaa && cleanFaa === activePopupIcao) || (popupAptCanonical && (popupAptCanonical.icao === apt.icao || popupAptCanonical.faa === apt.faa))));
      const inRadiusClass = (isInRadius || isOrigin || isDest || isPopupOpen || isRouteWaypoint) ? 'in-radius' : '';
      const originClass = (isOrigin && !isRouteWaypoint) ? 'is-origin' : '';
      const routeClass = isRouteWaypoint ? 'is-route-waypoint' : '';
      const zOffset = isLowest ? 12000 : (isPopupOpen ? 9500 : (isRouteWaypoint ? 11000 : (isOrigin ? 9000 : (isDest ? 8900 : (isInRadius ? 500 : 0)))));

      let markerObj = STATE.markers.get(apt.icao);

      if (!markerObj) {
        const iconHtml = `
          <div class="airport-marker-container ${tierClass} ${hasPriceClass} ${inRadiusClass} ${originClass} ${routeClass}" id="marker-${apt.icao}" title="${apt.icao} - ${apt.name} (${apt.city}, ${apt.state})">
            <div class="origin-ribbon" style="${isOrigin && !isRouteWaypoint ? 'display: flex;' : 'display: none;'}">🛫 ORIGIN</div>
            <div class="origin-pulse-ring" style="${isOrigin ? 'display: block;' : 'display: none;'}"></div>
            <div class="route-ribbon" style="${isRouteWaypoint ? 'display: flex;' : 'display: none;'}">${routeInfo ? routeInfo.label : ''}</div>
            <div class="lowest-ribbon" style="display: none;">🏆 LOWEST</div>
            <div class="pulse-ring" style="display: none;"></div>
            <div class="fuel-price-badge ${hasPriceClass} ${tierClass}">
              ${badgeInnerHtml}
            </div>
            <div class="marker-dot"></div>
          </div>
        `;

        const markerIcon = L.divIcon({
          className: 'custom-airport-div-icon',
          html: iconHtml,
          iconSize: [0, 0]
        });

        const marker = L.marker([apt.lat, apt.lon], { icon: markerIcon });
        marker.on('click', function (e) {
          if (e) {
            L.DomEvent.stopPropagation(e);
            if (e.originalEvent) {
              L.DomEvent.stopPropagation(e.originalEvent);
            }
          }
          fetchAirportFuelAndHighlight(apt);
        });
        marker.on('add', function () {
          attachMarkerDomListeners(apt.icao, apt);
        });

        marker.addTo(markersLayerGroup);
        markerObj = { marker, apt, tierClass, fuelInfo };
        STATE.markers.set(apt.icao, markerObj);
        if (isLowest) {
          markerObj.marker.setZIndexOffset(10000);
        } else if (isPopupOpen) {
          markerObj.marker.setZIndexOffset(9500);
        } else if (isRouteWaypoint) {
          markerObj.marker.setZIndexOffset(11000);
        } else if (isOrigin) {
          markerObj.marker.setZIndexOffset(9000);
        } else if (isDest) {
          markerObj.marker.setZIndexOffset(8900);
        } else if (isInRadius) {
          markerObj.marker.setZIndexOffset(500);
        } else {
          markerObj.marker.setZIndexOffset(0);
        }
        attachMarkerDomListeners(apt.icao, apt);
      } else {
        if (isLowest) {
          markerObj.marker.setZIndexOffset(10000);
        } else if (isPopupOpen) {
          markerObj.marker.setZIndexOffset(9500);
        } else if (isRouteWaypoint) {
          markerObj.marker.setZIndexOffset(11000);
        } else if (isOrigin) {
          markerObj.marker.setZIndexOffset(9000);
        } else if (isDest) {
          markerObj.marker.setZIndexOffset(8900);
        } else if (isInRadius) {
          markerObj.marker.setZIndexOffset(500);
        } else {
          markerObj.marker.setZIndexOffset(0);
        }
        markerObj.apt = apt;
        markerObj.tierClass = tierClass;
        markerObj.fuelInfo = fuelInfo;
        const el = document.getElementById(`marker-${apt.icao}`);
        if (el) {
          if (isInRadius || isOrigin || isDest || isPopupOpen || isRouteWaypoint) {
            el.classList.add('in-radius');
          } else {
            el.classList.remove('in-radius');
          }
          if (isOrigin && !isRouteWaypoint) {
            el.classList.add('is-origin');
            const oRibbon = el.querySelector('.origin-ribbon');
            const oRing = el.querySelector('.origin-pulse-ring');
            if (oRibbon) oRibbon.style.display = 'flex';
            if (oRing) oRing.style.display = 'block';
          } else {
            el.classList.remove('is-origin');
            const oRibbon = el.querySelector('.origin-ribbon');
            const oRing = el.querySelector('.origin-pulse-ring');
            if (oRibbon) oRibbon.style.display = 'none';
            if (oRing) oRing.style.display = isOrigin ? 'block' : 'none';
          }
          if (isRouteWaypoint) {
            el.classList.add('is-route-waypoint');
            let rRibbon = el.querySelector('.route-ribbon');
            if (!rRibbon) {
              rRibbon = document.createElement('div');
              rRibbon.className = 'route-ribbon';
              el.insertBefore(rRibbon, el.firstChild);
            }
            rRibbon.innerText = routeInfo.label;
            rRibbon.style.display = 'flex';
          } else {
            el.classList.remove('is-route-waypoint');
            const rRibbon = el.querySelector('.route-ribbon');
            if (rRibbon) rRibbon.style.display = 'none';
          }
          if (!el.classList.contains('is-loading')) {
            updateMarkerBadgeContent(apt);
          }
          attachMarkerDomListeners(apt.icao, apt, el);
        }
      }
    }

    // Update lowest marker if changed
    const currentLowestIcao = lowest ? lowest.icao : null;
    if (STATE.prevLowestIcao !== currentLowestIcao) {
      if (STATE.prevLowestIcao && STATE.prevLowestIcao !== currentLowestIcao) {
        const prevMarkerObj = STATE.markers.get(STATE.prevLowestIcao);
        if (prevMarkerObj && prevMarkerObj.marker) {
          const isPrevOrigin = originIcao && (STATE.prevLowestIcao === originIcao || (originFaa && STATE.prevLowestIcao === originFaa));
          const resetZ = isPrevOrigin ? 9000 : (currentInRadiusIcaos.has(STATE.prevLowestIcao) ? 500 : 0);
          prevMarkerObj.marker.setZIndexOffset(resetZ);
        }
        const prevEl = document.getElementById(`marker-${STATE.prevLowestIcao}`);
        if (prevEl) {
          prevEl.classList.remove('is-lowest');
          const ribbon = prevEl.querySelector('.lowest-ribbon');
          const ring = prevEl.querySelector('.pulse-ring');
          if (ribbon) ribbon.style.display = 'none';
          if (ring) ring.style.display = 'none';
        }
      }

      if (currentLowestIcao && lowest) {
        const lowestMarkerObj = STATE.markers.get(currentLowestIcao);
        if (lowestMarkerObj && lowestMarkerObj.marker) {
          lowestMarkerObj.marker.setZIndexOffset(10000);
        }
        const newEl = document.getElementById(`marker-${currentLowestIcao}`);
        if (newEl) {
          newEl.classList.add('is-lowest');
          newEl.classList.add('in-radius');
          const ribbon = newEl.querySelector('.lowest-ribbon');
          const ring = newEl.querySelector('.pulse-ring');
          if (ribbon) {
            ribbon.innerHTML = `🏆 BEST: $${lowest.effectiveFuel.price.toFixed(2)}`;
            ribbon.style.display = 'flex';
          }
          if (ring) ring.style.display = 'block';
        }
      }
      STATE.prevLowestIcao = currentLowestIcao;
    }

    STATE.prevInRadiusIcaos = currentInRadiusIcaos;
    STATE.activeHighlightedIcaos = currentHighlightedIcaos;

    // Redraw canvas dots (skipping active highlighted DOM markers)
    redrawAirportCanvas();

    // Origin vector line connecting circle center back towards Origin Airport
    updateOriginVectorLine();

    // Vector line connecting center to lowest price airport
    if (lowest && vectorLine) {
      vectorLine.setLatLngs([
        [centerLat, centerLon],
        [lowest.lat, lowest.lon]
      ]);
      vectorLine.setStyle({ opacity: 0.9 });
    } else if (vectorLine) {
      vectorLine.setLatLngs([]);
    }

    // Update Bottom Best Deal HUD & Sidebar List
    updateBestDealHUD(lowest, inRadiusList);
    updateSidebarRadarList(inRadiusList, lowest);
  }

  function getMarkerTierClass(apt, fuelInfo, isFetched) {
    if (fuelInfo && typeof fuelInfo.price === 'number' && !isNaN(fuelInfo.price)) {
      const p20 = STATE.p20 ?? 5.20;
      const p40 = STATE.p40 ?? 5.80;
      const p60 = STATE.p60 ?? 6.40;
      const p80 = STATE.p80 ?? 7.00;

      if (fuelInfo.price <= p20) return 'tier-ultra-cheap';
      if (fuelInfo.price <= p40) return 'tier-budget';
      if (fuelInfo.price <= p60) return 'tier-avg';
      if (fuelInfo.price <= p80) return 'tier-high';
      return 'tier-exp';
    }
    if (isFetched && (!apt.fbos || apt.fbos.length === 0)) {
      return 'tier-unreported';
    }
    return 'tier-ident';
  }

  function getBadgeHtml(apt, fuelInfo, isFetched) {
    const ident = apt.faa || apt.icao;
    const originInfo = getOriginDistanceInfo(apt);
    const routeInfo = getRouteStopInfo(apt);

    if (fuelInfo) {
      if (originInfo) {
        return `
          <span class="badge-code">${ident}</span>
          <span class="badge-sep">•</span>
          <span class="badge-dist">${originInfo.distFormatted}</span>
          <span class="badge-sep">•</span>
          <span class="badge-price">$${fuelInfo.price.toFixed(2)}</span>
          <span class="badge-fuel-type">${fuelInfo.type}</span>
        `;
      } else {
        return `
          <span class="badge-code">${ident}</span>
          <span class="badge-sep">•</span>
          <span class="badge-price">$${fuelInfo.price.toFixed(2)}</span>
          <span class="badge-fuel-type">${fuelInfo.type}</span>
        `;
      }
    } else if (routeInfo && routeInfo.price && routeInfo.price !== '--') {
      const priceStr = String(routeInfo.price).trim().startsWith('$') ? routeInfo.price : `$${routeInfo.price}`;
      return `
        <span class="badge-code">${ident}</span>
        <span class="badge-sep">•</span>
        <span class="badge-price">${priceStr}</span>
      `;
    } else if (isFetched && (!apt.fbos || apt.fbos.length === 0)) {
      if (originInfo) {
        return `
          <span class="badge-code">${ident}</span>
          <span class="badge-sep">•</span>
          <span class="badge-dist">${originInfo.distFormatted}</span>
          <span class="badge-sep">•</span>
          <span class="badge-price-unreported">No Fuel</span>
        `;
      } else {
        return `
          <span class="badge-code">${ident}</span>
          <span class="badge-sep">•</span>
          <span class="badge-price-unreported">No Fuel</span>
        `;
      }
    } else {
      if (originInfo) {
        return `
          <span class="badge-code">${ident}</span>
          <span class="badge-sep">•</span>
          <span class="badge-dist">${originInfo.distFormatted}</span>
        `;
      } else {
        return `
          <span class="badge-code">${ident}</span>
        `;
      }
    }
  }

  // --- Dynamic DOM Marker Update & On-Demand Fetch Handlers ---
  function setMarkerLoadingState(icao, isLoading) {
    const el = document.getElementById(`marker-${icao}`);
    if (!el) return;
    if (isLoading) {
      el.classList.add('is-loading');
      const badge = el.querySelector('.fuel-price-badge');
      if (badge) {
        const apt = STATE.airportsMap.get(icao);
        const ident = apt ? (apt.faa || apt.icao) : icao;
        badge.innerHTML = `
          <span class="badge-code">${ident}</span>
          <span class="badge-loading-spinner">⏳</span>
        `;
      }
    } else {
      el.classList.remove('is-loading');
      const apt = STATE.airportsMap.get(icao);
      if (apt) {
        updateMarkerBadgeContent(apt);
      }
    }
  }

  // --- Direct DOM Event Listener Attachment on Marker Badges ---
  function attachMarkerDomListeners(icao, apt, element = null) {
    const el = element || document.getElementById(`marker-${icao}`);
    if (!el) return;
    if (el._aerofuelListenerAttached) return;
    el._aerofuelListenerAttached = true;

    const handleAirportClick = function (e) {
      if (e) {
        if (e.stopPropagation) e.stopPropagation();
        if (e.preventDefault) e.preventDefault();
        if (typeof L !== 'undefined' && L.DomEvent) {
          if (L.DomEvent.stopPropagation) L.DomEvent.stopPropagation(e);
          if (L.DomEvent.preventDefault) L.DomEvent.preventDefault(e);
        }
      }
      fetchAirportFuelAndHighlight(apt);
    };

    const handlePointerDown = function (e) {
      if (e) {
        if (e.stopPropagation) e.stopPropagation();
        if (typeof L !== 'undefined' && L.DomEvent && L.DomEvent.stopPropagation) {
          L.DomEvent.stopPropagation(e);
        }
      }
    };

    el.addEventListener('click', handleAirportClick);
    el.addEventListener('pointerdown', handlePointerDown);
    el.addEventListener('touchstart', handlePointerDown, { passive: true });

    const badge = el.querySelector('.fuel-price-badge');
    if (badge) {
      badge.addEventListener('click', handleAirportClick);
      badge.addEventListener('pointerdown', handlePointerDown);
      badge.addEventListener('touchstart', handlePointerDown, { passive: true });
    }

    const ribbon = el.querySelector('.lowest-ribbon');
    if (ribbon) {
      ribbon.addEventListener('click', handleAirportClick);
      ribbon.addEventListener('pointerdown', handlePointerDown);
      ribbon.addEventListener('touchstart', handlePointerDown, { passive: true });
    }

    const originRibbon = el.querySelector('.origin-ribbon');
    if (originRibbon) {
      originRibbon.addEventListener('click', handleAirportClick);
      originRibbon.addEventListener('pointerdown', handlePointerDown);
      originRibbon.addEventListener('touchstart', handlePointerDown, { passive: true });
    }

    const routeRibbon = el.querySelector('.route-ribbon');
    if (routeRibbon) {
      routeRibbon.addEventListener('click', handleAirportClick);
      routeRibbon.addEventListener('pointerdown', handlePointerDown);
      routeRibbon.addEventListener('touchstart', handlePointerDown, { passive: true });
    }
  }

  function updateMarkerBadgeContent(apt) {
    const el = document.getElementById(`marker-${apt.icao}`);
    if (!el) return;
    const badge = el.querySelector('.fuel-price-badge');
    if (!badge) return;

    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const originIcao = STATE.originAirport ? (STATE.originAirport.icao || '').toUpperCase().trim() : null;
    const originFaa = STATE.originAirport ? (STATE.originAirport.faa || '').toUpperCase().trim() : null;
    const isOrigin = Boolean(originIcao && (cleanIcao === originIcao || (cleanFaa && cleanFaa === originFaa)));

    const isFetched = hasFetchedPrice(apt);
    const fuelInfo = isFetched ? getEffectiveFuelInfo(apt) : null;
    const tierClass = getMarkerTierClass(apt, fuelInfo, isFetched);
    const hasPriceClass = fuelInfo ? 'has-fuel-price' : 'no-fuel-price';
    const routeInfo = getRouteStopInfo(apt);
    const isRouteWaypoint = Boolean(routeInfo);

    // Reset tier and price classes
    el.classList.remove('tier-ultra-cheap', 'tier-budget', 'tier-cheap', 'tier-avg', 'tier-moderate', 'tier-high', 'tier-exp', 'tier-expensive', 'tier-unreported', 'tier-ident', 'is-loading', 'has-fuel-price', 'no-fuel-price');
    el.classList.add(tierClass, hasPriceClass);

    if (isOrigin && !isRouteWaypoint) {
      el.classList.add('is-origin');
      const oRibbon = el.querySelector('.origin-ribbon');
      const oRing = el.querySelector('.origin-pulse-ring');
      if (oRibbon) oRibbon.style.display = 'flex';
      if (oRing) oRing.style.display = 'block';
    } else {
      el.classList.remove('is-origin');
      const oRibbon = el.querySelector('.origin-ribbon');
      const oRing = el.querySelector('.origin-pulse-ring');
      if (oRibbon) oRibbon.style.display = 'none';
      if (oRing) oRing.style.display = isOrigin ? 'block' : 'none';
    }

    if (isRouteWaypoint) {
      el.classList.add('is-route-waypoint');
      let rRibbon = el.querySelector('.route-ribbon');
      if (!rRibbon) {
        rRibbon = document.createElement('div');
        rRibbon.className = 'route-ribbon';
        el.insertBefore(rRibbon, el.firstChild);
      }
      rRibbon.innerText = routeInfo.label;
      rRibbon.style.display = 'flex';
    } else {
      el.classList.remove('is-route-waypoint');
      const rRibbon = el.querySelector('.route-ribbon');
      if (rRibbon) rRibbon.style.display = 'none';
    }

    badge.className = `fuel-price-badge ${tierClass} ${hasPriceClass}`;
    badge.innerHTML = getBadgeHtml(apt, fuelInfo, isFetched);
    attachMarkerDomListeners(apt.icao, apt, el);
  }

  // --- Rich Map Bubble Tooltip / Popup Generator ---
  let activeAirportPopup = null;

  function generateAirportPopupHtml(apt, isLoading = false) {
    if (!apt) return '';
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;

    const identParts = [canonical.icao];
    if (canonical.faa && canonical.faa !== canonical.icao) {
      identParts.push(`/ ${canonical.faa}`);
    }
    if (canonical.iata && canonical.iata !== canonical.faa && canonical.iata !== canonical.icao) {
      identParts.push(`(${canonical.iata})`);
    }
    const identHeader = identParts.join(' ');
    const elev = canonical.elevation_ft !== undefined ? canonical.elevation_ft : 0;
    const elevText = `${elev.toLocaleString()} ft MSL`;
    const towerStatus = canonical.tower ? '🗼 Towered' : '📻 Non-Towered';
    // Frequency specs
    const isSingleAdvisory = !canonical.unicom_freq || !canonical.ctaf_freq || Math.abs(canonical.ctaf_freq - canonical.unicom_freq) < 0.001;
    const advisoryVal = canonical.ctaf_freq ? `${canonical.ctaf_freq.toFixed(2)} MHz` : (canonical.unicom_freq ? `${canonical.unicom_freq.toFixed(2)} MHz` : '122.80 MHz');
    const weatherVal = canonical.weather_freq ? `${canonical.weather_freq.toFixed(2)} MHz` : null;
    const weatherLabel = canonical.weather_type || 'AWOS/ATIS';
    const appVal = canonical.approach_freq ? `${canonical.approach_freq.toFixed(2)} MHz` : null;

    let freqSpecHtml = '';
    if (isSingleAdvisory) {
      freqSpecHtml = `
        <div class="popup-spec-pill" title="CTAF / UNICOM Advisory Radio Frequency">
          <span class="spec-k">📻 CTAF/UNICOM:</span>
          <span class="spec-v">${advisoryVal}</span>
          ${weatherVal ? `<span class="spec-k" style="margin-left: 8px;">🌤️ ${weatherLabel}:</span><span class="spec-v">${weatherVal}</span>` : ''}
          ${(!weatherVal && appVal) ? `<span class="spec-k" style="margin-left: 8px;">📡 APP:</span><span class="spec-v">${appVal}</span>` : ''}
        </div>
      `;
    } else {
      freqSpecHtml = `
        <div class="popup-spec-pill" title="CTAF & UNICOM Radio Frequencies">
          <span class="spec-k">📻 CTAF:</span>
          <span class="spec-v">${canonical.ctaf_freq ? canonical.ctaf_freq.toFixed(2) + ' MHz' : '122.80 MHz'}</span>
          <span class="spec-k" style="margin-left: 8px;">UNICOM:</span>
          <span class="spec-v">${canonical.unicom_freq ? canonical.unicom_freq.toFixed(2) + ' MHz' : '122.95 MHz'}</span>
          ${weatherVal ? `<span class="spec-k" style="margin-left: 8px;">🌤️ ${weatherLabel}:</span><span class="spec-v">${weatherVal}</span>` : ''}
        </div>
      `;
    }

    // Primary runway specs
    let primaryRunwayText = 'Runway info pending';
    if (canonical.runways && canonical.runways.length > 0) {
      const r = canonical.runways[0];
      const rwyLen = r.length ? `${r.length.toLocaleString()} ft` : '';
      const rwySurf = r.surface || 'Paved';
      primaryRunwayText = `${r.id || 'Primary'}: ${rwyLen} (${rwySurf})`;
      if (canonical.runways.length > 1) {
        primaryRunwayText += ` • +${canonical.runways.length - 1} more`;
      }
    }

    // Origin Distance Info (if configured)
    const originInfo = getOriginDistanceInfo(canonical);
    let originSpecHtml = '';
    if (originInfo) {
      originSpecHtml = `
        <div class="popup-spec-pill" title="Distance & Heading from Origin Airport (${originInfo.originIdent})">
          <span class="spec-k">🛫 From Origin (${originInfo.originIdent}):</span>
          <span class="spec-v" style="color: #38bdf8; font-weight: 700;">${originInfo.distFormatted} (${originInfo.bearing}° ${originInfo.direction})</span>
        </div>
      `;
    }

    // Fuel Price Breakdown
    let fuelsHtml = '';
    if (isLoading) {
      fuelsHtml = `
        <div class="popup-loading-box">
          <span class="badge-loading-spinner" style="font-size: 1.1rem; margin-right: 6px;">⏳</span>
          <span style="font-size: 0.82rem; color: #fff;">Fetching live AirNav rates for <strong>${canonical.icao}</strong>...</span>
        </div>
      `;
    } else if (canonical.fbos && canonical.fbos.length > 0) {
      let fboBlocks = '';
      for (let i = 0; i < canonical.fbos.length; i++) {
        const fbo = canonical.fbos[i];
        let fuelRows = '';
        const fuels = fbo.fuels || {};
        for (const [fkey, fobj] of Object.entries(fuels)) {
          if (!fobj || fobj.price === undefined) continue;
          const sLabel = fobj.service === 'Self-Serve' ? 'Self' : (fobj.service === 'Full-Serve' ? 'Full' : (fobj.service || ''));
          fuelRows += `
            <div class="popup-fuel-chip">
              <span class="popup-fuel-type-label">${fobj.type || fkey}</span>
              <span class="popup-fuel-service-label">${sLabel}</span>
              <span class="popup-fuel-price-val">$${fobj.price.toFixed(2)}</span>
            </div>
          `;
        }

        fboBlocks += `
          <div class="popup-fbo-card">
            <div class="popup-fbo-header">
              <span class="popup-fbo-name">🏢 ${fbo.name}</span>
              ${fbo.phone ? `<span class="popup-fbo-phone">📞 ${fbo.phone}</span>` : ''}
            </div>
            <div class="popup-fuels-grid">
              ${fuelRows || '<div class="popup-no-fuels">No fuel grades listed</div>'}
            </div>
          </div>
        `;
      }

      let freshnessBadge = '';
      if (canonical.fetched_at) {
        const rel = formatRelativeTime(canonical.fetched_at);
        const isCached = (Date.now() - new Date(canonical.fetched_at).getTime()) < 24 * 60 * 60 * 1000;
        freshnessBadge = `<span class="popup-timestamp-badge" title="Fetched: ${canonical.fetched_at}">⏱️ AirNav Quote: ${rel} ${isCached ? '(Cached)' : '(Stale)'}</span>`;
      } else {
        const timestamp = canonical.last_updated ? `AirNav: ${canonical.last_updated}` : 'AirNav Live Feed';
        const source = canonical.source ? ` (${canonical.source})` : '';
        freshnessBadge = `<span class="popup-timestamp-badge">${timestamp}${source}</span>`;
      }

      fuelsHtml = `
        <div class="popup-fuels-container">
          <div class="popup-fuels-title-bar">
            <span class="popup-fuels-heading">⛽ Fuel Prices & FBO Rates</span>
            ${freshnessBadge}
          </div>
          ${fboBlocks}
        </div>
      `;
    } else if (hasFetchedPrice(canonical)) {
      let freshnessBadge = '';
      if (canonical.fetched_at) {
        const rel = formatRelativeTime(canonical.fetched_at);
        const isCached = (Date.now() - new Date(canonical.fetched_at).getTime()) < 24 * 60 * 60 * 1000;
        freshnessBadge = ` • ⏱️ ${rel} ${isCached ? '(Cached)' : '(Stale)'}`;
      }
      fuelsHtml = `
        <div class="popup-unreported-notice">
          <span>ℹ️ AirNav reported no active commercial FBO fuel pricing${freshnessBadge}</span>
        </div>
      `;
    } else {
      fuelsHtml = `
        <div class="popup-unfetched-notice">
          <span>⚡ Click below to fetch live AirNav rates</span>
        </div>
      `;
    }

    return `
      <div class="airport-popup-bubble-content" data-icao="${canonical.icao}">
        <!-- Airport Header -->
        <div class="popup-header-block">
          <div class="popup-ident-row">
            <span class="popup-ident-main">${identHeader}</span>
            <span class="popup-tower-tag ${canonical.tower ? 'is-towered' : 'is-nontowered'}">${towerStatus}</span>
          </div>
          <div class="popup-name-title">${canonical.name || `${canonical.icao} Airport`}</div>
          <div class="popup-meta-subtitle">📍 ${canonical.city ? canonical.city + ', ' : ''}${canonical.state || ''} • Elev: ${elevText}</div>
        </div>

        <!-- Quick Specs -->
        <div class="popup-specs-grid">
          ${originSpecHtml}
          <div class="popup-spec-pill" title="Primary Runway Dimensions and Surface">
            <span class="spec-k">🛫 Runway:</span>
            <span class="spec-v">${primaryRunwayText}</span>
          </div>
          ${freqSpecHtml}
        </div>

        <!-- Fuel Breakdown -->
        ${fuelsHtml}

        <!-- Actions -->
        <div class="popup-action-row">
          <button class="btn-popup-set-origin" id="popup-btn-origin-${canonical.icao}" data-icao="${canonical.icao}" title="Set as origin airport for distance reference">
            🛫 Set Origin
          </button>
          <button class="btn-popup-refresh" id="popup-btn-refresh-${canonical.icao}" data-icao="${canonical.icao}" title="Bypass 24h cache and fetch fresh live AirNav rates" ${isLoading ? 'disabled' : ''}>
            🔄 Refresh Live
          </button>
          <button class="btn-popup-open-details" id="popup-btn-details-${canonical.icao}" data-icao="${canonical.icao}">
            📋 Open Full Details
          </button>
        </div>
      </div>
    `;
  }

  function openAirportPopup(apt, isLoading = false) {
    if (!map || !apt) return;
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;

    // Close existing popup if currently open for a different airport
    if (activeAirportPopup && activeAirportPopup.isOpen() && STATE.activePopupIcao && STATE.activePopupIcao !== canonical.icao) {
      map.closePopup(activeAirportPopup);
    }

    STATE.activePopupIcao = canonical.icao;

    let markerObj = STATE.markers.get(cleanIcao) || (cleanFaa ? STATE.markers.get(cleanFaa) : null);
    if (!markerObj) {
      recalculateRadiusAirports();
      markerObj = STATE.markers.get(cleanIcao) || (cleanFaa ? STATE.markers.get(cleanFaa) : null);
    }

    const popupHtml = generateAirportPopupHtml(canonical, isLoading);

    const popupOptions = {
      className: 'aerofuel-rich-popup',
      maxWidth: 380,
      minWidth: 290,
      autoPan: true,
      autoPanPadding: [20, 80],
      offset: [0, -12],
      closeOnClick: false,
      autoClose: false,
      closeButton: true
    };

    if (markerObj && markerObj.marker) {
      if (!markerObj.marker.getPopup()) {
        markerObj.marker.bindPopup(popupHtml, popupOptions);
      } else {
        markerObj.marker.setPopupContent(popupHtml);
      }
      markerObj.marker.openPopup();
      activeAirportPopup = markerObj.marker.getPopup();
    } else {
      activeAirportPopup = L.popup(popupOptions)
        .setLatLng([canonical.lat, canonical.lon])
        .setContent(popupHtml)
        .openOn(map);
    }

    if (activeAirportPopup) {
      isolatePopupEvents(activeAirportPopup);
    }

    ensureAirportDetails(canonical).then(updatedApt => {
      if (STATE.activePopupIcao === updatedApt.icao) {
        updateActivePopupContent(updatedApt);
      }
    });
  }

  function updateActivePopupContent(apt) {
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;
    const markerObj = STATE.markers.get(cleanIcao) || (cleanFaa ? STATE.markers.get(cleanFaa) : null);
    if (markerObj && markerObj.marker && markerObj.marker.getPopup()) {
      markerObj.marker.setPopupContent(generateAirportPopupHtml(canonical, false));
    }
    if (activeAirportPopup && activeAirportPopup.isOpen()) {
      const el = activeAirportPopup.getElement();
      if (!el || el.querySelector(`[data-icao="${cleanIcao}"]`) || (cleanFaa && el.querySelector(`[data-icao="${cleanFaa}"]`))) {
        activeAirportPopup.setContent(generateAirportPopupHtml(canonical, false));
      }
    }
  }

  async function fetchAirportFuelAndHighlight(apt, forceRefresh = false, openModalDirectly = false) {
    if (!apt) return;
    const icao = apt.icao;
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || cleanIcao).toUpperCase().trim();
    const ident = apt.faa || apt.icao;

    // Retrieve or establish canonical master airport object
    let targetApt = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;

    // Ensure fetched_at is synchronized across object references and customPrices
    if (!targetApt.fetched_at) {
      targetApt.fetched_at = apt.fetched_at ||
        (STATE.customPrices[cleanIcao] && STATE.customPrices[cleanIcao].fetched_at) ||
        (cleanFaa && STATE.customPrices[cleanFaa] && STATE.customPrices[cleanFaa].fetched_at) ||
        null;
    }
    if (!apt.fetched_at && targetApt.fetched_at) {
      apt.fetched_at = targetApt.fetched_at;
    }

    // Check 24-hour cache window:
    // If airport already has fuel/pricing data and a fetched_at timestamp within 24 hours,
    // skip network request completely, instantly open the rich popup with 0ms latency, and update marker badge.
    const hasFuelData = (targetApt.fbos && targetApt.fbos.length > 0) || (targetApt.best_price !== null && targetApt.best_price !== undefined) || hasFetchedPrice(targetApt);
    let isFresh = false;
    if (targetApt.fetched_at) {
      const fetchedTime = new Date(targetApt.fetched_at).getTime();
      if (!isNaN(fetchedTime)) {
        const ageMs = Date.now() - fetchedTime;
        if (ageMs >= 0 && ageMs < 24 * 60 * 60 * 1000) {
          isFresh = true;
        }
      }
    }

    if (!forceRefresh && isFresh && hasFuelData) {
      // 0ms latency instant cache hit: open rich popup attached to marker
      openAirportPopup(targetApt, false);
      if (openModalDirectly) {
        openAirportModal(targetApt, false);
      }
      updateMarkerBadgeContent(targetApt);
      if (!STATE.radarEnabled || window.innerWidth <= 860) {
        showSelectedAirportHUD(targetApt);
      }
      return targetApt;
    }

    // 1. Show sleek loading indicator directly on clicked bubble tag
    setMarkerLoadingState(icao, true);
    setMarkerLoadingState(cleanIcao, true);

    // 2. Open rich Leaflet popup attached to marker with loading state
    openAirportPopup(targetApt, true);
    if (!STATE.radarEnabled || window.innerWidth <= 860) {
      showSelectedAirportHUD(targetApt);
    }

    // 3. Open modal directly only if explicitly requested (e.g. from popup button or direct trigger)
    if (openModalDirectly) {
      openAirportModal(targetApt, true);
    }

    try {
      let fetchUrl = `/api/airnav?icao=${encodeURIComponent(cleanIcao)}`;
      if (forceRefresh) {
        fetchUrl += '&refresh=1';
      }

      const res = await fetch(fetchUrl);
      if (res.ok) {
        const jsonRes = await res.json();
        if (jsonRes.status === 'ok') {
          const returnedAirports = (Array.isArray(jsonRes.airports) && jsonRes.airports.length > 0) ? jsonRes.airports : (jsonRes.data ? [jsonRes.data] : []);
          const fetchedTimestamp = jsonRes.fetched_at || (jsonRes.data && jsonRes.data.fetched_at) || new Date().toISOString();

          if (returnedAirports.length > 0) {
            for (let i = 0; i < returnedAirports.length; i++) {
              const d = returnedAirports[i];
              if (!d || !d.icao) continue;

              const itemIcao = (d.icao || '').toUpperCase().trim();
              const itemFaa = (d.faa || itemIcao).toUpperCase().trim();

              let itemApt = STATE.airportsMap.get(itemIcao) || (itemFaa ? STATE.airportsMap.get(itemFaa) : null);
              if (!itemApt) {
                if (itemIcao.startsWith('K') && itemIcao.length === 4) {
                  itemApt = STATE.airportsMap.get(itemIcao.slice(1));
                } else if (itemIcao.length === 3) {
                  itemApt = STATE.airportsMap.get('K' + itemIcao);
                }
              }

              if (!itemApt) {
                itemApt = {
                  icao: itemIcao,
                  faa: itemFaa,
                  iata: d.iata || '',
                  name: d.name || `${itemIcao} Airport`,
                  city: d.city || '',
                  state: d.state || '',
                  country: d.country || 'US',
                  lat: d.lat || 0.0,
                  lon: d.lon || 0.0,
                  elevation_ft: d.elevation_ft || 0,
                  ctaf_freq: d.ctaf_freq || 122.8,
                  unicom_freq: d.unicom_freq || 122.8,
                  runways: d.runways || [],
                  fbos: d.fbos || [],
                  best_price: d.best_price !== undefined ? d.best_price : null,
                  primary_fuel: d.primary_fuel || (d.best_price ? '100LL' : 'None'),
                  fuels_available: d.fuels_available || [],
                  last_updated: d.last_updated || new Date().toISOString().split('T')[0],
                  fetched_at: d.fetched_at || fetchedTimestamp,
                  source: d.source || "AirNav Local Fuel"
                };
                STATE.airports.push(itemApt);
                STATE.airportsMap.set(itemIcao, itemApt);
                if (itemFaa) STATE.airportsMap.set(itemFaa, itemApt);
              } else {
                if (d.fbos && d.fbos.length > 0) {
                  itemApt.fbos = d.fbos;
                  itemApt.best_price = d.best_price;
                  itemApt.primary_fuel = d.primary_fuel || "100LL";
                  itemApt.fuels_available = d.fuels_available || [];
                } else if (d.best_price !== undefined) {
                  itemApt.best_price = d.best_price;
                  itemApt.primary_fuel = d.primary_fuel || itemApt.primary_fuel || "None";
                }
                itemApt.last_updated = d.last_updated || new Date().toISOString().split('T')[0];
                itemApt.fetched_at = d.fetched_at || fetchedTimestamp;
                itemApt.source = d.source || itemApt.source || "AirNav Local Fuel";
                if (d.ctaf_freq) itemApt.ctaf_freq = d.ctaf_freq;
                if (d.unicom_freq) itemApt.unicom_freq = d.unicom_freq;
                if (d.name && (!itemApt.name || itemApt.name.includes("Airport"))) itemApt.name = d.name;
              }

              // Persist in session state across both ICAO and FAA keys
              STATE.fetchedAirports.add(itemIcao);
              if (itemFaa) STATE.fetchedAirports.add(itemFaa);
              if (itemApt.icao) STATE.fetchedAirports.add(itemApt.icao.toUpperCase().trim());
              if (itemApt.faa) STATE.fetchedAirports.add(itemApt.faa.toUpperCase().trim());

              // Ensure both ICAO and FAA are in STATE.airportsMap
              STATE.airportsMap.set(itemIcao, itemApt);
              if (itemFaa) STATE.airportsMap.set(itemFaa, itemApt);
              if (itemApt.icao) STATE.airportsMap.set(itemApt.icao.toUpperCase().trim(), itemApt);
              if (itemApt.faa) STATE.airportsMap.set(itemApt.faa.toUpperCase().trim(), itemApt);

              const keysToSet = new Set([itemIcao]);
              if (itemFaa) keysToSet.add(itemFaa);
              if (itemApt.icao) keysToSet.add(itemApt.icao.toUpperCase().trim());
              if (itemApt.faa) keysToSet.add(itemApt.faa.toUpperCase().trim());

              keysToSet.forEach(k => {
                if (!STATE.customPrices[k]) {
                  STATE.customPrices[k] = {};
                }
                STATE.customPrices[k].fetched_at = itemApt.fetched_at;
              });

              if (d.fbos && d.fbos.length > 0) {
                for (const fbo of d.fbos) {
                  for (const [fkey, fval] of Object.entries(fbo.fuels || {})) {
                    if (fval && fval.price !== undefined) {
                      keysToSet.forEach(k => {
                        STATE.customPrices[k][fkey] = fval.price;
                      });
                    }
                  }
                }
              }
            }

            // Batch save all updated airports to localStorage
            savePersistedAirportsBatchToStorage(returnedAirports);

            // Re-establish targetApt reference for the clicked airport
            targetApt = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || targetApt;
            apt.fetched_at = targetApt.fetched_at;
            Object.assign(apt, targetApt);

            // Synchronize spatial index, percentiles, radius markers, and canvas dots
            buildSpatialGridIndex();
            updatePricePercentiles();
            recalculateRadiusAirports();
            renderAllAirportMarkers();
            redrawAirportCanvas();
            updateMarkerBadgeContent(targetApt);
            openAirportPopup(targetApt, false);
            updateActivePopupContent(targetApt);

            // Update badge content on any instantiated markers in returned batch
            for (let i = 0; i < returnedAirports.length; i++) {
              const ret = returnedAirports[i];
              if (ret && ret.icao) {
                const retApt = STATE.airportsMap.get(ret.icao.toUpperCase().trim());
                if (retApt) {
                  updateMarkerBadgeContent(retApt);
                }
              }
            }

            if (STATE.activeAirportModal && (STATE.activeAirportModal.icao === cleanIcao || STATE.activeAirportModal.faa === cleanFaa)) {
              openAirportModal(targetApt, false);
            }

            const isFallback = Boolean(jsonRes.fallback || (returnedAirports.length === 1 && jsonRes.radius_miles === 0));
            const radiusMiles = jsonRes.radius_miles !== undefined ? jsonRes.radius_miles : 45;

            if (returnedAirports.length > 1 && !isFallback) {
              showToast(`⚡ AirNav Local: Updated ${returnedAirports.length} airports within ${radiusMiles} miles of ${ident}!`);
            } else if (returnedAirports.length === 1 && !isFallback && radiusMiles > 0) {
              showToast(`⚡ AirNav Local: Updated 1 airport within ${radiusMiles} miles of ${ident}!`);
            } else {
              const effective = getEffectiveFuelInfo(targetApt);
              const priceStr = effective ? `$${effective.price.toFixed(2)}/gal` : (targetApt.best_price ? `$${targetApt.best_price.toFixed(2)}/gal` : '');
              const srcLabel = targetApt.source ? ` (${targetApt.source})` : '';
              showToast(`⚡ AirNav: Updated rates for ${ident}${priceStr ? ' (' + priceStr + ')' : ''}${srcLabel}`);
            }
            return targetApt;
          } else {
            STATE.fetchedAirports.add(icao);
            STATE.fetchedAirports.add(cleanIcao);
            if (cleanFaa) STATE.fetchedAirports.add(cleanFaa);

            targetApt.fbos = [];
            targetApt.best_price = null;
            targetApt.primary_fuel = "None";
            targetApt.fuels_available = [];
            targetApt.last_updated = new Date().toISOString().split('T')[0];
            targetApt.fetched_at = fetchedTimestamp;
            targetApt.source = "AirNav Local Fuel";
            apt.fetched_at = fetchedTimestamp;
            Object.assign(apt, targetApt);

            if (!STATE.customPrices[icao]) {
              STATE.customPrices[icao] = {};
            }
            STATE.customPrices[icao].fetched_at = fetchedTimestamp;
            if (!STATE.customPrices[cleanIcao]) {
              STATE.customPrices[cleanIcao] = {};
            }
            STATE.customPrices[cleanIcao].fetched_at = fetchedTimestamp;
            if (cleanFaa) {
              if (!STATE.customPrices[cleanFaa]) {
                STATE.customPrices[cleanFaa] = {};
              }
              STATE.customPrices[cleanFaa].fetched_at = fetchedTimestamp;
            }

            savePersistedAirportToStorage(targetApt);
            savePersistedAirportToStorage(apt);

            buildSpatialGridIndex();
            recalculateRadiusAirports();
            redrawAirportCanvas();
            updateMarkerBadgeContent(targetApt);
            updateActivePopupContent(targetApt);

            if (STATE.activeAirportModal && (STATE.activeAirportModal.icao === cleanIcao || STATE.activeAirportModal.faa === cleanFaa)) {
              openAirportModal(targetApt, false);
            }
            showToast(`ℹ️ AirNav reported no active retail FBO pricing for ${ident}`);
            return targetApt;
          }
        } else {
          showToast(`⚠️ AirNav response: ${jsonRes.message || 'No data'}`);
        }
      } else {
        showToast(`⚠️ Could not reach AirNav proxy (/api/airnav). Ensure server.py is running.`);
      }
    } catch (err) {
      showToast(`⚠️ AirNav fetch failed (${err.message}). Is server.py running?`);
    } finally {
      setMarkerLoadingState(icao, false);
      setMarkerLoadingState(cleanIcao, false);
      updateActivePopupContent(targetApt);
      if (!STATE.radarEnabled || window.innerWidth <= 860) {
        showSelectedAirportHUD(targetApt);
      }
      if (STATE.activeAirportModal && (STATE.activeAirportModal.icao === cleanIcao || STATE.activeAirportModal.faa === cleanFaa)) {
        openAirportModal(targetApt, false);
      }
    }
  }

  // --- UI Update Functions ---
  function updateBestDealHUD(lowest, inRadiusList) {
    const hud = document.getElementById('best-deal-hud');
    if (!hud) return;

    if (!lowest) {
      hud.style.display = 'none';
      document.body.classList.remove('has-active-airport-hud');
      STATE.prevBestDealSignature = '';
      return;
    }

    hud.style.display = 'flex';
    document.body.classList.add('has-active-airport-hud');

    // Calculate average price in radius for savings calculation (only among priced airports)
    const pricedInRadius = inRadiusList.filter(a => a.hasFuel);
    const avgPrice = pricedInRadius.reduce((acc, a) => acc + a.effectiveFuel.price, 0) / (pricedInRadius.length || 1);
    const savingsPerGal = Math.max(0, avgPrice - lowest.effectiveFuel.price);
    const savings50Gal = savingsPerGal * 50;

    const signature = `${STATE.radiusUnit}:${lowest.icao}:${lowest.effectiveFuel.price}:${lowest.distanceMiles.toFixed(1)}:${inRadiusList.length}:${avgPrice.toFixed(2)}`;
    if (STATE.prevBestDealSignature === signature) return;
    STATE.prevBestDealSignature = signature;

    hud.innerHTML = `
      <div class="best-deal-badge">
        <span class="best-deal-badge-title">🏆 Lowest In Radius</span>
        <span class="best-deal-price">$${lowest.effectiveFuel.price.toFixed(2)}</span>
        <span class="best-deal-fuel-type">${lowest.effectiveFuel.label || lowest.effectiveFuel.type}</span>
      </div>
      <div class="best-deal-info">
        <div class="best-deal-header">
          <span class="best-deal-icao">${lowest.icao}</span>
          <span class="best-deal-name" title="${lowest.name}">${lowest.name}</span>
        </div>
        <div class="best-deal-sub">
          <span>${lowest.city}, ${lowest.state}</span>
          <span>•</span>
          <span class="best-deal-dist">📍 ${formatDistance(lowest.distanceMiles)} (${lowest.bearing}° ${lowest.direction})</span>
          <span>•</span>
          <span>${lowest.effectiveFuel.fboName || 'FBO'}</span>
        </div>
        <div class="best-deal-savings">
          ${savingsPerGal > 0.05 ? `💰 Saves <strong>$${savingsPerGal.toFixed(2)}/gal</strong> ($${savings50Gal.toFixed(2)} on 50 gal) vs radius avg ($${avgPrice.toFixed(2)})` : `⭐ Lowest rate among ${pricedInRadius.length} reporting fuel in area`}
        </div>
      </div>
      <div class="best-deal-actions">
        <button class="btn-hud btn-hud-primary" id="btn-fly-lowest" title="Center map on airport">
          <span>🎯 Center</span>
        </button>
        <button class="btn-hud" id="btn-details-lowest" title="Open airport specs & fuel modal">
          <span>📋 Specs</span>
        </button>
        <button class="btn-hud btn-hud-close" id="btn-close-best-deal" title="Dismiss" aria-label="Dismiss">
          <span>✕</span>
        </button>
      </div>
    `;

    document.getElementById('btn-fly-lowest').addEventListener('click', () => {
      map.flyTo([lowest.lat, lowest.lon], 11, { duration: 1.2 });
      STATE.circleCenter = { lat: lowest.lat, lng: lowest.lon };
      STATE.isLocked = true;
      updateCirclePosition(lowest.lat, lowest.lon);
      updateUIControls();
      recalculateRadiusAirports();
    });

    document.getElementById('btn-details-lowest').addEventListener('click', () => {
      openAirportModal(lowest);
    });

    const closeBtn = document.getElementById('btn-close-best-deal');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        hud.style.display = 'none';
        document.body.classList.remove('has-active-airport-hud');
        STATE.prevBestDealSignature = '';
      });
    }
  }

  function showSelectedAirportHUD(apt) {
    const hud = document.getElementById('best-deal-hud');
    if (!hud || !apt) return;

    STATE.selectedAirport = apt;
    hud.style.display = 'flex';
    document.body.classList.add('has-active-airport-hud');

    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || cleanIcao).toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;

    const isFetched = hasFetchedPrice(canonical);
    const fuelInfo = isFetched ? getEffectiveFuelInfo(canonical) : null;

    // Distance calculation from Origin or Circle Center
    let distDisplay = '';
    const refPoint = STATE.originAirport || STATE.circleCenter;
    if (refPoint && canonical.lat && canonical.lon) {
      const distMiles = haversineMiles(refPoint.lat, refPoint.lon || refPoint.lng, canonical.lat, canonical.lon);
      const bearing = calculateBearing(refPoint.lat, refPoint.lon || refPoint.lng, canonical.lat, canonical.lon);
      const dir = getCompassDirection(bearing);
      distDisplay = `<span>•</span><span class="best-deal-dist">📍 ${formatDistance(distMiles)} (${bearing}° ${dir})</span>`;
    }

    // Price badge display
    let badgeClass = 'best-deal-badge';
    let badgeTitle = '📍 Airport Info';
    let priceDisplay = '--';
    let fuelTypeDisplay = 'Avgas';

    if (fuelInfo && typeof fuelInfo.price === 'number') {
      badgeTitle = '⛽ Avgas Rate';
      priceDisplay = `$${fuelInfo.price.toFixed(2)}`;
      fuelTypeDisplay = fuelInfo.label || fuelInfo.type || '100LL';
      badgeClass += ' has-price';
    } else if (canonical.best_price !== null && canonical.best_price !== undefined) {
      badgeTitle = '⛽ Best Price';
      priceDisplay = `$${Number(canonical.best_price).toFixed(2)}`;
      fuelTypeDisplay = 'Avgas';
      badgeClass += ' has-price';
    } else if (isFetched) {
      badgeTitle = '⛽ No Fuel';
      priceDisplay = 'No Avgas';
      fuelTypeDisplay = 'Commercial';
      badgeClass += ' no-fuel';
    } else {
      badgeTitle = '📍 Unsearched';
      priceDisplay = 'Click Rates';
      fuelTypeDisplay = 'AirNav Lookup';
      badgeClass += ' unsearched';
    }

    const fboName = (fuelInfo && fuelInfo.fboName) || (canonical.fbos && canonical.fbos[0] && canonical.fbos[0].name) || 'Airport';

    // Specs line: runways, CTAF, elevation
    const elev = canonical.elevation_ft ? `${canonical.elevation_ft} ft elev` : '';
    const freq = (canonical.ctaf_freq || canonical.unicom_freq) ? `CTAF ${canonical.ctaf_freq || canonical.unicom_freq} MHz` : '';
    const rwy = (canonical.runways && canonical.runways.length > 0) ? `${canonical.runways.length} Rwy${canonical.runways.length > 1 ? 's' : ''}` : '';
    const specsLine = [elev, freq, rwy].filter(Boolean).join(' • ') || 'Aviation Fuel & Facilities';

    hud.innerHTML = `
      <div class="${badgeClass}">
        <span class="best-deal-badge-title">${badgeTitle}</span>
        <span class="best-deal-price">${priceDisplay}</span>
        <span class="best-deal-fuel-type">${fuelTypeDisplay}</span>
      </div>
      <div class="best-deal-info">
        <div class="best-deal-header">
          <span class="best-deal-icao">${canonical.icao || canonical.faa}</span>
          <span class="best-deal-name" title="${canonical.name}">${canonical.name}</span>
        </div>
        <div class="best-deal-sub">
          <span>${canonical.city || ''}${canonical.state ? ', ' + canonical.state : ''}</span>
          ${distDisplay}
          <span>•</span>
          <span>${fboName}</span>
        </div>
        <div class="best-deal-savings">
          ${specsLine}
        </div>
      </div>
      <div class="best-deal-actions">
        <button class="btn-hud btn-hud-primary" id="btn-fly-selected" title="Center map on airport">
          <span>🎯 Center</span>
        </button>
        <button class="btn-hud" id="btn-details-selected" title="Open airport specs & fuel modal">
          <span>📋 Specs</span>
        </button>
        <button class="btn-hud btn-hud-close" id="btn-close-selected" title="Dismiss" aria-label="Dismiss">
          <span>✕</span>
        </button>
      </div>
    `;

    document.getElementById('btn-fly-selected').addEventListener('click', () => {
      map.flyTo([canonical.lat, canonical.lon], Math.max(map.getZoom(), 11), { duration: 1.0 });
      if (STATE.radarEnabled) {
        STATE.circleCenter = { lat: canonical.lat, lng: canonical.lon };
        STATE.isLocked = true;
        updateCirclePosition(canonical.lat, canonical.lon);
        updateUIControls();
        recalculateRadiusAirports();
      }
    });

    document.getElementById('btn-details-selected').addEventListener('click', () => {
      openAirportModal(canonical);
    });

    const closeBtn = document.getElementById('btn-close-selected');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        STATE.selectedAirport = null;
        hud.style.display = 'none';
        document.body.classList.remove('has-active-airport-hud');
        recalculateRadiusAirports();
      });
    }
  }

  function updateSidebarRadarList(inRadiusList, lowest) {
    const countEl = document.getElementById('stat-airports-count');
    const minPriceEl = document.getElementById('stat-min-price');
    const avgPriceEl = document.getElementById('stat-avg-price');
    const listContainer = document.getElementById('radar-airports-list');
    const headerBadge = document.getElementById('sidebar-header-badge');

    if (!STATE.radarEnabled) {
      if (countEl) {
        countEl.innerText = '0';
        countEl.title = 'Search Radar is currently turned off';
      }
      if (headerBadge) {
        headerBadge.innerText = 'OFF';
        headerBadge.title = 'Search Radar is turned off';
      }
      const mobileBadge = document.getElementById('mobile-airports-badge');
      if (mobileBadge) {
        mobileBadge.innerText = 'OFF';
      }
      if (minPriceEl) minPriceEl.innerText = '--';
      if (avgPriceEl) avgPriceEl.innerText = '--';

      if (listContainer) {
        if (STATE.prevSidebarSignature !== 'radar-off') {
          STATE.prevSidebarSignature = 'radar-off';
          listContainer.innerHTML = `
            <div style="text-align: center; padding: 32px 16px; color: var(--text-dim); font-size: 0.85rem;">
              <div style="font-size: 2.2rem; margin-bottom: 10px; opacity: 0.6;">📡</div>
              <p style="font-weight: 700; color: var(--text-bright); margin-bottom: 6px;">Radar Is Turned Off</p>
              <p style="font-size: 0.75rem; color: var(--text-muted); line-height: 1.4;">Turn on the Search Radar in the top-left pane to scan for nearby airports and live fuel deals.</p>
              <button id="btn-sidebar-enable-radar" class="btn-hud btn-hud-primary" style="margin-top: 14px; width: 100%; justify-content: center;">
                <span>📡 Turn Radar ON</span>
              </button>
            </div>
          `;
          const enableBtn = document.getElementById('btn-sidebar-enable-radar');
          if (enableBtn) {
            enableBtn.addEventListener('click', () => {
              setRadarEnabled(true);
            });
          }
        }
      }
      return;
    }

    const priced = inRadiusList.filter(a => a.hasFuel && a.effectiveFuel);
    const unfetched = inRadiusList.filter(a => !a.isFetched);
    const confirmedNoFuel = inRadiusList.filter(a => a.isFetched && !a.hasFuel);

    if (countEl) {
      countEl.innerText = priced.length;
      if (unfetched.length > 0 || confirmedNoFuel.length > 0) {
        countEl.title = `${priced.length} reporting fuel (${inRadiusList.length} total airfields in radius; ${unfetched.length} unfetched)`;
      } else {
        countEl.title = `${priced.length} airports reporting fuel`;
      }
    }

    if (headerBadge) {
      headerBadge.innerText = priced.length;
      headerBadge.title = `${priced.length} reporting fuel (${inRadiusList.length} total in radius)`;
    }
    const mobileBadge = document.getElementById('mobile-airports-badge');
    if (mobileBadge) {
      mobileBadge.innerText = priced.length;
    }

    if (priced.length > 0) {
      const prices = priced.map(a => a.effectiveFuel.price);
      const minP = Math.min(...prices);
      const avgP = prices.reduce((a, b) => a + b, 0) / prices.length;
      if (minPriceEl) minPriceEl.innerText = `$${minP.toFixed(2)}`;
      if (avgPriceEl) avgPriceEl.innerText = `$${avgP.toFixed(2)}`;
    } else {
      if (minPriceEl) minPriceEl.innerText = '--';
      if (avgPriceEl) avgPriceEl.innerText = '--';
    }

    if (!listContainer) return;

    if (inRadiusList.length === 0) {
      if (STATE.prevSidebarSignature !== 'empty') {
        STATE.prevSidebarSignature = 'empty';
        listContainer.innerHTML = `
          <div style="text-align: center; padding: 30px 16px; color: var(--text-dim); font-size: 0.85rem;">
            <div style="font-size: 2rem; margin-bottom: 8px;">📡</div>
            <p>No airports found in current ${STATE.radiusValue} ${STATE.radiusUnit} radius circle.</p>
            <p style="font-size: 0.75rem; margin-top: 6px; color: var(--text-muted);">Increase the radius slider or move your mouse over other flight regions.</p>
          </div>
        `;
      }
      return;
    }

    // Create signature to avoid destroying DOM and losing scroll position
    const originKey = STATE.originAirport ? STATE.originAirport.icao : 'no-origin';
    const signature = `${originKey}:${STATE.radiusUnit}:` + inRadiusList.map(a => `${a.icao}:${a.hasFuel ? a.effectiveFuel.price.toFixed(2) : (a.isFetched ? 'nofuel' : 'unfetched')}:${a.distanceMiles.toFixed(1)}`).join('|');
    if (STATE.prevSidebarSignature === signature) {
      return;
    }
    STATE.prevSidebarSignature = signature;

    let html = '';
    let pricedRank = 1;

    // 1. Primary Section: Active reporting fuel prices
    if (priced.length > 0) {
      priced.forEach((apt) => {
        const isLowest = lowest && apt.icao === lowest.icao;
        const rankBadge = isLowest ? '🏆' : `#${pricedRank++}`;
        let tierCardClass = 'tier-avg';
        if (apt.effectiveFuel) {
          tierCardClass = getMarkerTierClass(apt, apt.effectiveFuel, true);
        }
        const cardClass = isLowest
          ? `radar-airport-card is-lowest-card has-fuel-card has-fuel-price ${tierCardClass}`
          : `radar-airport-card has-fuel-card has-fuel-price ${tierCardClass}`;
        const originInfo = getOriginDistanceInfo(apt);
        const originTag = originInfo ? `<span>•</span> <span style="color: #38bdf8; font-weight: 600;" title="Distance from Origin ${originInfo.originIdent}">🛫 ${originInfo.distFormatted}</span>` : '';

        html += `
          <div class="${cardClass}" data-icao="${apt.icao}" title="Click to view specs and highlight ${apt.icao}">
            <div class="card-rank">${rankBadge}</div>
            <div class="card-main">
              <div class="card-title-row">
                <span class="card-icao">${apt.faa || apt.icao}</span>
                <span class="card-name" title="${apt.name}">${apt.name}</span>
              </div>
              <div class="card-sub-row">
                <span>${apt.city}, ${apt.state}</span>
                <span>•</span>
                <span style="color: var(--accent-cyan);">📍 ${formatDistance(apt.distanceMiles)}</span>
                ${originTag}
                <span>•</span>
                <span>${apt.effectiveFuel.service}</span>
              </div>
            </div>
            <div class="card-price-section">
              <div class="card-price">$${apt.effectiveFuel.price.toFixed(2)}</div>
              <div class="card-fuel-label">${apt.effectiveFuel.type}</div>
            </div>
          </div>
        `;
      });
    }

    // 2. Secondary Section: In Radius Unfetched Airfields (Click to Fetch AirNav Live Rate)
    if (unfetched.length > 0) {
      html += `
        <div class="sidebar-section-divider">
          <span>In Radius • Click to Fetch Live AirNav Rates (${unfetched.length})</span>
        </div>
      `;
      unfetched.forEach((apt) => {
        const originInfo = getOriginDistanceInfo(apt);
        const originTag = originInfo ? `<span>•</span> <span style="color: #38bdf8; font-weight: 600;" title="Distance from Origin ${originInfo.originIdent}">🛫 ${originInfo.distFormatted}</span>` : '';

        html += `
          <div class="radar-airport-card is-unfetched-card" data-icao="${apt.icao}" title="Click to fetch live AirNav pricing for ${apt.icao}">
            <div class="card-rank" style="color: var(--accent-cyan); font-size: 0.85rem;">⚡</div>
            <div class="card-main">
              <div class="card-title-row">
                <span class="card-icao" style="color: var(--accent-cyan);">${apt.faa || apt.icao}</span>
                <span class="card-name" title="${apt.name}">${apt.name}</span>
              </div>
              <div class="card-sub-row">
                <span>${apt.city}, ${apt.state}</span>
                <span>•</span>
                <span style="color: var(--accent-cyan);">📍 ${formatDistance(apt.distanceMiles)}</span>
                ${originTag}
                <span>•</span>
                <span style="color: var(--text-muted);">AirNav On-Demand</span>
              </div>
            </div>
            <div class="card-price-section">
              <div class="card-price-fetch">⚡ Fetch Rate</div>
            </div>
          </div>
        `;
      });
    }

    // 3. Tertiary Section: Confirmed No Fuel on AirNav
    if (confirmedNoFuel.length > 0) {
      html += `
        <div class="sidebar-section-divider">
          <span>No Retail Fuel Reported (${confirmedNoFuel.length})</span>
        </div>
      `;
      confirmedNoFuel.forEach((apt) => {
        const originInfo = getOriginDistanceInfo(apt);
        const originTag = originInfo ? `<span>•</span> <span style="color: #38bdf8; font-weight: 600;" title="Distance from Origin ${originInfo.originIdent}">🛫 ${originInfo.distFormatted}</span>` : '';

        html += `
          <div class="radar-airport-card is-unreported-card" data-icao="${apt.icao}" title="AirNav reported no retail fuel pricing for ${apt.icao}">
            <div class="card-rank" style="color: var(--text-dim);">—</div>
            <div class="card-main">
              <div class="card-title-row">
                <span class="card-icao" style="color: var(--text-muted);">${apt.faa || apt.icao}</span>
                <span class="card-name" title="${apt.name}">${apt.name}</span>
              </div>
              <div class="card-sub-row">
                <span>${apt.city}, ${apt.state}</span>
                <span>•</span>
                <span style="color: var(--accent-cyan);">📍 ${formatDistance(apt.distanceMiles)}</span>
                ${originTag}
                <span>•</span>
                <span style="color: var(--text-dim);">No Fuel</span>
              </div>
            </div>
            <div class="card-price-section">
              <div class="card-price-unreported">No Fuel</div>
              <div class="card-type-unreported">Unreported</div>
            </div>
          </div>
        `;
      });
    }

    listContainer.innerHTML = html;

    // Attach click listeners to cards
    listContainer.querySelectorAll('.radar-airport-card').forEach(card => {
      card.addEventListener('click', () => {
        const icao = card.getAttribute('data-icao');
        const apt = STATE.airportsMap.get(icao);
        if (apt) {
          map.flyTo([apt.lat, apt.lon], 11, { duration: 1 });
          fetchAirportFuelAndHighlight(apt);
        }
      });
    });
  }

  function updateUIControls() {
    const hud = document.getElementById('radius-control-hud');
    const radarPowerBtn = document.getElementById('btn-radar-power');
    const slider = document.getElementById('radius-slider');
    const displayNum = document.getElementById('radius-display-num');
    const displayUnit = document.getElementById('radius-display-unit');
    const lockBtn = document.getElementById('btn-lock-toggle');
    const lockBadge = document.getElementById('lock-status-badge');

    if (hud) {
      if (STATE.radarEnabled) {
        hud.classList.remove('radar-off');
      } else {
        hud.classList.add('radar-off');
      }
    }

    if (radarPowerBtn) {
      if (STATE.radarEnabled) {
        radarPowerBtn.className = 'btn-radar-power active';
        radarPowerBtn.innerHTML = '<span class="power-dot"></span><span class="power-label">Radar ON</span>';
        radarPowerBtn.setAttribute('title', 'Turn Radar OFF (Shortcut: R)');
      } else {
        radarPowerBtn.className = 'btn-radar-power off';
        radarPowerBtn.innerHTML = '<span class="power-dot"></span><span class="power-label">Radar OFF</span>';
        radarPowerBtn.setAttribute('title', 'Turn Radar ON (Shortcut: R)');
      }
    }

    const mobileRadarBtn = document.getElementById('mobile-btn-radar');
    if (mobileRadarBtn) {
      if (STATE.radarEnabled) {
        mobileRadarBtn.className = 'mobile-bar-btn active';
        mobileRadarBtn.innerHTML = '<span class="bar-icon">📡</span><span class="bar-label">Radar ON</span>';
        mobileRadarBtn.setAttribute('title', 'Turn Radar OFF');
      } else {
        mobileRadarBtn.className = 'mobile-bar-btn off';
        mobileRadarBtn.innerHTML = '<span class="bar-icon">⚪</span><span class="bar-label">Radar OFF</span>';
        mobileRadarBtn.setAttribute('title', 'Turn Radar ON');
      }
    }

    if (slider) {
      slider.value = STATE.radiusValue;
      slider.disabled = !STATE.radarEnabled;
    }
    if (displayNum) displayNum.innerText = STATE.radiusValue;
    if (displayUnit) displayUnit.innerText = STATE.radiusUnit;

    if (lockBtn) {
      lockBtn.innerHTML = STATE.isLocked ? '<span>🔓 Unlock (Follow Mouse)</span>' : '<span>📍 Lock Position</span>';
      if (STATE.isLocked) {
        lockBtn.classList.add('active');
      } else {
        lockBtn.classList.remove('active');
      }
      lockBtn.disabled = !STATE.radarEnabled;
    }

    if (lockBadge) {
      if (!STATE.radarEnabled) {
        lockBadge.className = 'lock-status-badge disabled';
        lockBadge.innerHTML = '<span>⚪ Radar Disabled</span>';
      } else if (STATE.isLocked) {
        lockBadge.className = 'lock-status-badge locked';
        lockBadge.innerHTML = '<span>📍 Position Locked</span>';
      } else {
        lockBadge.className = 'lock-status-badge following';
        lockBadge.innerHTML = '<span>📡 Following Mouse</span>';
      }
    }

    // Radius circle size & visibility
    if (radiusCircle) {
      radiusCircle.setRadius(getRadiusInMeters());
      if (STATE.radarEnabled) {
        radiusCircle.setStyle({ opacity: 0.85, fillOpacity: 0.12 });
      } else {
        radiusCircle.setStyle({ opacity: 0, fillOpacity: 0 });
      }
    }

    if (centerReticleMarker) {
      centerReticleMarker.setOpacity(STATE.radarEnabled ? 1 : 0);
    }

    // Unit toggle buttons
    document.querySelectorAll('.unit-btn').forEach(btn => {
      if (btn.getAttribute('data-unit') === STATE.radiusUnit) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Preset chip buttons
    document.querySelectorAll('.chip-btn').forEach(btn => {
      const val = parseInt(btn.getAttribute('data-val'), 10);
      if (val === STATE.radiusValue) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
      btn.disabled = !STATE.radarEnabled;
    });
  }

  function ensureAirportDetails(apt) {
    if (!apt) return Promise.resolve(apt);
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;
    if (canonical._detailsLoaded || (canonical.runways && canonical.runways.length > 0 && canonical.frequencies && canonical.frequencies.length > 0)) {
      canonical._detailsLoaded = true;
      return Promise.resolve(canonical);
    }
    if (canonical._detailsPromise) {
      return canonical._detailsPromise;
    }

    canonical._detailsPromise = fetch(`/api/airport/${encodeURIComponent(cleanIcao)}`)
      .then(res => res.json())
      .then(data => {
        if (data && data.status === 'ok' && data.airport) {
          Object.assign(canonical, data.airport);
          canonical._detailsLoaded = true;
        }
        return canonical;
      })
      .catch(() => canonical)
      .finally(() => {
        canonical._detailsPromise = null;
      });

    return canonical._detailsPromise;
  }

  // --- Airport Detail Modal ---
  function openAirportModal(apt, isLoading = false) {
    if (!apt) return;
    if (typeof window.closeAllMobileDrawers === 'function') {
      window.closeAllMobileDrawers();
    }
    if (activeAirportPopup && map) {
      map.closePopup(activeAirportPopup);
      activeAirportPopup = null;
      STATE.activePopupIcao = null;
    }
    const cleanIcao = (apt.icao || '').toUpperCase().trim();
    const cleanFaa = (apt.faa || '').toUpperCase().trim();
    const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;
    apt = canonical;
    STATE.activeAirportModal = apt;

    // Asynchronously ensure full details (runways, frequencies, FBOs) are loaded and update modal
    ensureAirportDetails(canonical).then(updatedApt => {
      if (STATE.activeAirportModal === updatedApt) {
        renderModalContent(updatedApt, isLoading);
      }
    });

    renderModalContent(canonical, isLoading);
  }

  function renderModalContent(apt, isLoading = false) {
    const modalBackdrop = document.getElementById('airport-modal-backdrop');
    if (!modalBackdrop) return;

    // Runways text
    const runwaysList = (apt.runways || []).map(r => `<strong>${r.id}</strong>: ${r.length.toLocaleString()} ft (${r.surface})`).join(' • ') || 'Runway data pending';

    // FBO Cards HTML
    let fbosHtml = '';
    if (isLoading) {
      fbosHtml = `
        <div class="fbo-card" style="text-align: center; padding: 24px 16px; border: 1.5px dashed var(--accent-cyan); background: rgba(2, 132, 199, 0.12);">
          <div class="badge-loading-spinner" style="font-size: 1.6rem; margin-bottom: 8px;">⏳</div>
          <div style="font-weight: 700; color: #fff; font-size: 0.95rem; margin-bottom: 4px;">Fetching Live AirNav Fuel Rates...</div>
          <p style="font-size: 0.78rem; color: var(--text-muted); line-height: 1.4;">
            Connecting to AirNav real-time retail FBO pricing feed for <strong>${apt.icao}</strong>...
          </p>
        </div>
      `;
    } else if (apt.fbos && apt.fbos.length > 0) {
      apt.fbos.forEach(fbo => {
        let fuelsRows = '';
        for (const [key, f] of Object.entries(fbo.fuels || {})) {
          fuelsRows += `
            <tr>
              <td><strong>${f.label || key}</strong></td>
              <td class="service-cell">${f.service || 'Standard'}</td>
              <td class="price-cell">$${f.price.toFixed(2)}/gal</td>
            </tr>
          `;
        }

        fbosHtml += `
          <div class="fbo-card">
            <div class="fbo-header">
              <span class="fbo-name">🏢 ${fbo.name}</span>
              <span class="fbo-phone">📞 ${fbo.phone}</span>
            </div>
            ${fbo.notes ? `<p style="font-size: 0.76rem; color: var(--text-muted); margin-bottom: 6px;">ℹ️ ${fbo.notes}</p>` : ''}
            <table class="fuels-table">
              <thead>
                <tr>
                  <th>Fuel Grade</th>
                  <th>Service</th>
                  <th>Price</th>
                </tr>
              </thead>
              <tbody>
                ${fuelsRows}
              </tbody>
            </table>
          </div>
        `;
      });
    } else {
      fbosHtml = `
        <div class="fbo-unreported-notice">
          <div style="font-size: 1.3rem; margin-bottom: 6px;">ℹ️</div>
          <div style="font-weight: 700; color: #fff; font-size: 0.9rem; margin-bottom: 4px;">No Commercial Fuel Rates Reported</div>
          <p style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;">
            AirNav reported no active retail FBO fuel pricing logged for this airfield.
            Contact the local airport sponsor or monitor CTAF <strong>${apt.ctaf_freq ? apt.ctaf_freq.toFixed(2) + ' MHz' : '122.80 MHz'}</strong> for local fuel availability.
          </p>
        </div>
      `;
    }

    const identParts = [apt.icao];
    if (apt.faa && apt.faa !== apt.icao) {
      identParts.push(`/ ${apt.faa}`);
    }
    if (apt.iata && apt.iata !== apt.faa && apt.iata !== apt.icao) {
      identParts.push(`• IATA: ${apt.iata}`);
    }
    const identHeader = identParts.join(' ');

    const originInfo = getOriginDistanceInfo(apt);
    let originSpecModal = '';
    if (originInfo) {
      originSpecModal = `
        <div class="spec-item" style="border-color: rgba(56, 189, 248, 0.4); background: rgba(2, 132, 199, 0.15);">
          <div class="spec-title" style="color: #38bdf8;">Distance from Origin (${originInfo.originIdent})</div>
          <div class="spec-val" style="color: #fff; font-weight: 700;">🛫 ${originInfo.distFormatted} (${originInfo.bearing}° ${originInfo.direction})</div>
        </div>
      `;
    }

    let freshnessBadgeModal = '';
    if (apt.fetched_at) {
      const rel = formatRelativeTime(apt.fetched_at);
      const isCached = (Date.now() - new Date(apt.fetched_at).getTime()) < 24 * 60 * 60 * 1000;
      freshnessBadgeModal = `<span class="modal-freshness-badge" title="Fetched at: ${apt.fetched_at}">⏱️ AirNav Quote: ${rel} ${isCached ? '(Cached)' : '(Stale)'}</span>`;
    }

    const isSingleAdvisoryModal = !apt.unicom_freq || !apt.ctaf_freq || Math.abs(apt.ctaf_freq - apt.unicom_freq) < 0.001;
    const advisoryValModal = apt.ctaf_freq ? `${apt.ctaf_freq.toFixed(2)} MHz` : (apt.unicom_freq ? `${apt.unicom_freq.toFixed(2)} MHz` : '122.80 MHz');
    
    let advisorySpecModal = '';
    if (isSingleAdvisoryModal) {
      advisorySpecModal = `
        <div class="spec-item">
          <div class="spec-title">CTAF / UNICOM</div>
          <div class="spec-val">${advisoryValModal}</div>
        </div>
      `;
    } else {
      advisorySpecModal = `
        <div class="spec-item">
          <div class="spec-title">CTAF Frequency</div>
          <div class="spec-val">${apt.ctaf_freq ? apt.ctaf_freq.toFixed(2) + ' MHz' : '122.80 MHz'}</div>
        </div>
        <div class="spec-item">
          <div class="spec-title">UNICOM / Radio</div>
          <div class="spec-val">${apt.unicom_freq ? apt.unicom_freq.toFixed(2) + ' MHz' : '122.95 MHz'}</div>
        </div>
      `;
    }

    let weatherSpecModal = '';
    if (apt.weather_freq) {
      const wType = apt.weather_type || 'AWOS / ATIS';
      weatherSpecModal = `
        <div class="spec-item">
          <div class="spec-title">${wType} Weather</div>
          <div class="spec-val">${apt.weather_freq.toFixed(2)} MHz</div>
        </div>
      `;
    }

    let approachSpecModal = '';
    if (apt.approach_freq) {
      approachSpecModal = `
        <div class="spec-item">
          <div class="spec-title">Approach / Radar</div>
          <div class="spec-val">${apt.approach_freq.toFixed(2)} MHz</div>
        </div>
      `;
    } else if (apt.ground_freq) {
      approachSpecModal = `
        <div class="spec-item">
          <div class="spec-title">Ground Control</div>
          <div class="spec-val">${apt.ground_freq.toFixed(2)} MHz</div>
        </div>
      `;
    }

    let frequenciesHtml = '';
    if (apt.frequencies && apt.frequencies.length > 0) {
      const freqChips = apt.frequencies.map(f => {
        const typeLabel = f.type || 'RADIO';
        const mhz = typeof f.frequency_mhz === 'number' ? f.frequency_mhz.toFixed(2) : f.frequency_mhz;
        const desc = f.description && f.description !== f.type ? ` title="${f.description}"` : '';
        return `
          <div class="popup-fuel-chip" style="padding: 4px 8px; border-radius: var(--radius-sm); font-size: 0.78rem;"${desc}>
            <span class="popup-fuel-type-label" style="font-weight: 700;">${typeLabel}</span>
            <span class="popup-fuel-price-val" style="color: #38bdf8; font-family: monospace;">${mhz} MHz</span>
            ${f.description && f.description !== f.type ? `<span style="font-size: 0.7rem; color: var(--text-muted); margin-left: 4px;">(${f.description})</span>` : ''}
          </div>
        `;
      }).join('');

      frequenciesHtml = `
        <div style="margin-top: 10px;">
          <div class="section-heading">📻 All Radio Communications (${apt.frequencies.length})</div>
          <div style="background: rgba(30, 41, 59, 0.4); border: 1px solid var(--card-border); border-radius: var(--radius-md); padding: 8px 10px; display: flex; flex-wrap: wrap; gap: 6px;">
            ${freqChips}
          </div>
        </div>
      `;
    }

    modalBackdrop.innerHTML = `
      <div class="modal-card">
        <div class="modal-header">
          <div class="modal-title-wrap">
            <h2>✈️ ${apt.name} (${identHeader})</h2>
            <div class="modal-subtitle">📍 ${apt.city}, ${apt.state}, USA • Elev: ${apt.elevation_ft} ft MSL</div>
          </div>
          <button class="modal-close-btn" id="modal-close-x">&times;</button>
        </div>
        <div class="modal-body">
          <!-- Quick Specs Grid -->
          <div class="specs-grid">
            ${originSpecModal}
            <div class="spec-item">
              <div class="spec-title">Tower / Control</div>
              <div class="spec-val">${apt.tower ? '🗼 Towered' : '📻 Non-Towered'}</div>
            </div>
            ${advisorySpecModal}
            ${weatherSpecModal}
            ${approachSpecModal}
            <div class="spec-item">
              <div class="spec-title">Coordinates</div>
              <div class="spec-val">${apt.lat.toFixed(4)}°, ${apt.lon.toFixed(4)}°</div>
            </div>
          </div>

          <!-- Runways -->
          <div>
            <div class="section-heading">🛫 Runways</div>
            <div style="background: rgba(30, 41, 59, 0.4); border: 1px solid var(--card-border); border-radius: var(--radius-md); padding: 10px; font-size: 0.85rem;">
              ${runwaysList}
            </div>
          </div>

          <!-- All Radio Communications -->
          ${frequenciesHtml}

          <!-- FBO & Fuel Rates -->
          <div>
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; flex-wrap: wrap; gap: 4px;">
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                <div class="section-heading" style="margin-bottom: 0;">⛽ FBO Directory & Fuel Rates</div>
                ${freshnessBadgeModal}
              </div>
              <button class="btn-hud btn-hud-airnav" id="btn-fetch-live-airnav" style="font-size: 0.74rem; padding: 4px 10px;" title="Fetch Live AirNav Price • Bypass 24h cache" ${isLoading ? 'disabled' : ''}>
                <span>${isLoading ? '⏳ Fetching...' : (hasFetchedPrice(apt) ? '🔄 Refresh Live' : '⚡ Fetch Live AirNav Price')}</span>
              </button>
            </div>
            ${fbosHtml}
          </div>
        </div>
        <div class="modal-footer">
          <div class="external-links">
            <a href="https://www.airnav.com/airport/${apt.icao}" target="_blank" rel="noopener" class="link-pill">🌐 AirNav</a>
            <a href="https://skyvector.com/?ll=${apt.lat},${apt.lon}&chart=301&zoom=2" target="_blank" rel="noopener" class="link-pill">🗺️ SkyVector Chart</a>
            <a href="https://flightaware.com/live/airport/${apt.icao}" target="_blank" rel="noopener" class="link-pill">📡 FlightAware</a>
          </div>
          <button class="btn-hud" id="btn-modal-set-origin" title="Set as origin airport for distance calculation">
            <span>🛫 Set as Origin</span>
          </button>
          <button class="btn-hud btn-hud-primary" id="btn-modal-set-center">
            <span>🎯 Set Radar Center Here</span>
          </button>
        </div>
      </div>
    `;

    modalBackdrop.classList.add('open');

    // Close listeners
    document.getElementById('modal-close-x').addEventListener('click', closeModal);
    modalBackdrop.addEventListener('click', function (e) {
      if (e.target === modalBackdrop) closeModal();
    });

    // Set Origin Button Listener
    const btnSetOrigin = document.getElementById('btn-modal-set-origin');
    if (btnSetOrigin) {
      btnSetOrigin.addEventListener('click', () => {
        setOriginAirport(apt);
        closeModal();
      });
    }

    // AirNav Live Fetch Button Listener
    const btnAirNav = document.getElementById('btn-fetch-live-airnav');
    if (btnAirNav) {
      btnAirNav.addEventListener('click', async function () {
        this.disabled = true;
        this.innerHTML = '<span>⏳ Fetching AirNav...</span>';
        try {
          await fetchAirportFuelAndHighlight(apt, true);
        } catch (err) {
          showToast(`⚠️ Live AirNav fetch failed (${err.message}). Is server.py running?`);
        } finally {
          const btn = document.getElementById('btn-fetch-live-airnav');
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span>🔄 Refresh Live</span>';
          }
        }
      });
    }

    document.getElementById('btn-modal-set-center').addEventListener('click', () => {
      STATE.circleCenter = { lat: apt.lat, lng: apt.lon };
      STATE.isLocked = true;
      updateCirclePosition(apt.lat, apt.lon);
      map.flyTo([apt.lat, apt.lon], 10, { duration: 1 });
      updateUIControls();
      recalculateRadiusAirports();
      closeModal();
      showToast(`📍 Search circle centered on ${apt.icao} (${apt.name})`);
    });
  }

  function closeModal() {
    const modalBackdrop = document.getElementById('airport-modal-backdrop');
    if (modalBackdrop) modalBackdrop.classList.remove('open');
    STATE.activeAirportModal = null;
    recalculateRadiusAirports();
  }

  // --- Search Autocomplete ---
  function setupSearch() {
    const searchInput = document.getElementById('airport-search');
    const dropdown = document.getElementById('search-dropdown');
    if (!searchInput || !dropdown) return;

    searchInput.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 1) {
        dropdown.style.display = 'none';
        dropdown.innerHTML = '';
        return;
      }

      const matches = STATE.airports.filter(a => {
        return (
          a.icao.toLowerCase().includes(q) ||
          (a.faa && a.faa.toLowerCase().includes(q)) ||
          (a.iata && a.iata.toLowerCase().includes(q)) ||
          a.name.toLowerCase().includes(q) ||
          a.city.toLowerCase().includes(q) ||
          a.state.toLowerCase().includes(q)
        );
      }).slice(0, 8);

      if (matches.length === 0) {
        dropdown.innerHTML = `<div style="padding: 10px; font-size: 0.8rem; color: var(--text-dim);">No matching airports found</div>`;
        dropdown.style.display = 'block';
        return;
      }

      let html = '';
      matches.forEach(apt => {
        const fuel = getEffectiveFuelInfo(apt);
        const priceStr = fuel ? `$${fuel.price.toFixed(2)}` : (hasFetchedPrice(apt) ? 'No Fuel Data' : '⚡ On-Demand');
        html += `
          <div class="search-item" data-icao="${apt.icao}">
            <span class="search-item-code">${apt.faa || apt.icao}</span>
            <div class="search-item-info">
              <div><strong>${apt.name}</strong></div>
              <div>${apt.city}, ${apt.state}</div>
            </div>
            <span class="search-item-price ${fuel ? '' : 'search-item-unreported'}">${priceStr}</span>
          </div>
        `;
      });

      dropdown.innerHTML = html;
      dropdown.style.display = 'block';

      dropdown.querySelectorAll('.search-item').forEach(item => {
        item.addEventListener('click', function () {
          const icao = this.getAttribute('data-icao');
          const apt = STATE.airportsMap.get(icao);
          if (apt) {
            searchInput.value = `${apt.icao} - ${apt.name}`;
            dropdown.style.display = 'none';
            map.flyTo([apt.lat, apt.lon], 11, { duration: 1.2 });
            STATE.circleCenter = { lat: apt.lat, lng: apt.lon };
            STATE.isLocked = true;
            updateCirclePosition(apt.lat, apt.lon);
            updateUIControls();
            recalculateRadiusAirports();
            fetchAirportFuelAndHighlight(apt);
          }
        });
      });
    });

    document.addEventListener('click', function (e) {
      if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    });
  }

  // --- Origin Airport Autocomplete & Input Setup ---
  function setupOriginSearch() {
    const input = document.getElementById('origin-airport-input');
    const dropdown = document.getElementById('origin-search-dropdown');
    const clearBtn = document.getElementById('btn-clear-origin');
    if (!input || !dropdown) return;

    input.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 1) {
        dropdown.style.display = 'none';
        dropdown.innerHTML = '';
        return;
      }

      const matches = STATE.airports.filter(a => {
        return (
          a.icao.toLowerCase().includes(q) ||
          (a.faa && a.faa.toLowerCase().includes(q)) ||
          (a.iata && a.iata.toLowerCase().includes(q)) ||
          a.name.toLowerCase().includes(q) ||
          a.city.toLowerCase().includes(q) ||
          a.state.toLowerCase().includes(q)
        );
      }).slice(0, 8);

      if (matches.length === 0) {
        dropdown.innerHTML = `<div style="padding: 10px; font-size: 0.8rem; color: var(--text-dim);">No matching airports found</div>`;
        dropdown.style.display = 'block';
        return;
      }

      let html = '';
      matches.forEach(apt => {
        const ident = apt.faa || apt.icao;
        html += `
          <div class="search-item origin-search-item" data-icao="${apt.icao}">
            <span class="search-item-code">${ident}</span>
            <div class="search-item-info">
              <div><strong>${apt.name}</strong></div>
              <div>${apt.city}, ${apt.state}</div>
            </div>
            <span class="search-item-price" style="font-size: 0.72rem; color: var(--accent-cyan);">Set Origin</span>
          </div>
        `;
      });

      dropdown.innerHTML = html;
      dropdown.style.display = 'block';

      dropdown.querySelectorAll('.origin-search-item').forEach(item => {
        item.addEventListener('click', function () {
          const icao = this.getAttribute('data-icao');
          const apt = STATE.airportsMap.get(icao);
          if (apt) {
            setOriginAirport(apt);
            dropdown.style.display = 'none';
          }
        });
      });
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        const q = this.value.trim();
        if (q) {
          setOriginAirport(q);
          dropdown.style.display = 'none';
          input.blur();
        } else {
          clearOriginAirport();
          dropdown.style.display = 'none';
          input.blur();
        }
      } else if (e.key === 'Escape') {
        dropdown.style.display = 'none';
      }
    });

    input.addEventListener('change', function () {
      if (!this.value.trim()) {
        clearOriginAirport();
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        clearOriginAirport();
      });
    }

    document.addEventListener('click', function (e) {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    });
  }

  // --- Destination Airport Autocomplete & Input Setup ---
  function setupDestinationSearch() {
    const input = document.getElementById('destination-airport-input');
    const dropdown = document.getElementById('destination-search-dropdown');
    const clearBtn = document.getElementById('btn-clear-destination');
    if (!input || !dropdown) return;

    input.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      if (q.length < 1) {
        dropdown.style.display = 'none';
        dropdown.innerHTML = '';
        return;
      }

      const matches = STATE.airports.filter(a => {
        return (
          a.icao.toLowerCase().includes(q) ||
          (a.faa && a.faa.toLowerCase().includes(q)) ||
          (a.iata && a.iata.toLowerCase().includes(q)) ||
          a.name.toLowerCase().includes(q) ||
          a.city.toLowerCase().includes(q) ||
          a.state.toLowerCase().includes(q)
        );
      }).slice(0, 8);

      if (matches.length === 0) {
        dropdown.innerHTML = `<div style="padding: 10px; font-size: 0.8rem; color: var(--text-dim);">No matching airports found</div>`;
        dropdown.style.display = 'block';
        return;
      }

      let html = '';
      matches.forEach(apt => {
        const ident = apt.faa || apt.icao;
        html += `
          <div class="search-item destination-search-item" data-icao="${apt.icao}">
            <span class="search-item-code">${ident}</span>
            <div class="search-item-info">
              <div><strong>${apt.name}</strong></div>
              <div>${apt.city}, ${apt.state}</div>
            </div>
            <span class="search-item-price" style="font-size: 0.72rem; color: #38bdf8;">Set Destination</span>
          </div>
        `;
      });

      dropdown.innerHTML = html;
      dropdown.style.display = 'block';

      dropdown.querySelectorAll('.destination-search-item').forEach(item => {
        item.addEventListener('click', function () {
          const icao = this.getAttribute('data-icao');
          const apt = STATE.airportsMap.get(icao);
          if (apt) {
            setDestinationAirport(apt);
            dropdown.style.display = 'none';
          }
        });
      });
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        const q = this.value.trim();
        if (q) {
          setDestinationAirport(q);
          dropdown.style.display = 'none';
          input.blur();
        } else {
          clearDestinationAirport();
          dropdown.style.display = 'none';
          input.blur();
        }
      } else if (e.key === 'Escape') {
        dropdown.style.display = 'none';
      }
    });

    input.addEventListener('change', function () {
      if (!this.value.trim()) {
        clearDestinationAirport();
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        clearDestinationAirport();
      });
    }

    document.addEventListener('click', function (e) {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    });
  }

  // --- Route Planner Controls Setup ---
  function setupRoutePlanner() {
    const btnPlan = document.getElementById('btn-plan-route');
    const btnClear = document.getElementById('btn-clear-route');

    if (btnPlan) {
      btnPlan.addEventListener('click', function (e) {
        e.preventDefault();
        planFuelRoute();
      });
    }

    if (btnClear) {
      btnClear.addEventListener('click', function (e) {
        e.preventDefault();
        clearFuelRoute();
      });
    }
  }

  // --- Load Latest Fuel Prices / Data Source Modal ---
  function setupDataSourceModal() {
    const btnLoadPrices = document.getElementById('btn-load-prices');
    const modalBackdrop = document.getElementById('data-source-modal-backdrop');
    if (!btnLoadPrices || !modalBackdrop) return;

    btnLoadPrices.addEventListener('click', () => {
      openDataSourceModal();
    });
  }

  function openDataSourceModal() {
    if (typeof window.closeAllMobileDrawers === 'function') {
      window.closeAllMobileDrawers();
    }
    const modalBackdrop = document.getElementById('data-source-modal-backdrop');
    if (!modalBackdrop) return;

    modalBackdrop.innerHTML = `
      <div class="modal-card" style="max-width: 580px;">
        <div class="modal-header">
          <div class="modal-title-wrap">
            <h2>⚡ Fuel Price Feeds & Data Sources</h2>
            <div class="modal-subtitle">Sync, update, or import latest national aviation fuel rates</div>
          </div>
          <button class="modal-close-btn" id="ds-modal-close">&times;</button>
        </div>
        <div class="modal-body">
          <!-- Option 0: Authoritative OurAirports Directory & Frequencies Sync -->
          <div class="fbo-card" style="background: rgba(16, 185, 129, 0.14); border: 1.5px solid rgba(16, 185, 129, 0.55); box-shadow: 0 0 15px rgba(16, 185, 129, 0.15);">
            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap;">
              <div style="flex: 1; min-width: 260px;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                  <h4 style="color: #fff; font-size: 0.96rem; margin: 0;">🌐 OurAirports Master Directory & Frequencies</h4>
                  <span class="badge-recommended" style="background: #059669; border-color: #34d399;">SOURCE OF TRUTH</span>
                </div>
                <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px; line-height: 1.35;">
                  Syncs <code>airports.csv</code>, <code>airport-frequencies.csv</code>, and <code>runways.csv</code> directly from <a href="https://ourairports.com/data/" target="_blank" rel="noopener" style="color: #34d399; text-decoration: underline;">OurAirports.com/data/</a> to refresh all US public airports, coordinates, authoritative runway data, and communication frequencies (Tower, CTAF, UNICOM, Ground, ATIS).
                </p>
                <div id="ourairports-sync-meta" style="font-size: 0.73rem; color: #a7f3d0; margin-top: 4px; font-family: var(--font-mono);">
                  📅 Last Downloaded: <span id="ourairports-last-updated-text">Checking status...</span>
                </div>
              </div>
              <button class="btn-hud" id="btn-sync-ourairports" style="margin-top: 4px; white-space: nowrap; border-color: rgba(16, 185, 129, 0.6); background: rgba(16, 185, 129, 0.25); color: #6ee7b7;">
                <span>⬇️ Update from OurAirports</span>
              </button>
            </div>
          </div>

          <!-- Option 1: Primary AirNav Live Sync -->
          <div class="fbo-card" style="background: rgba(2, 132, 199, 0.18); border: 1.5px solid rgba(56, 189, 248, 0.6); box-shadow: 0 0 15px rgba(2, 132, 199, 0.15);">
            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;">
              <div style="flex: 1;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                  <h4 style="color: #fff; font-size: 0.96rem; margin: 0;">📡 AirNav Live Sync</h4>
                  <span class="badge-recommended">PRIMARY SOURCE</span>
                </div>
                <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 8px;">
                  Fetches real-time retail 100LL (Self/Full), UL94, 100UL, 100R, Mogas, and Jet-A prices directly from AirNav for airports in your active search radar (${STATE.airportsInRadius.length} airports).
                </p>

                <div id="airnav-status-label" style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 8px;">
                  Primary Source: AirNav Live (https://www.airnav.com) • Real-time Retail Feed
                </div>
              </div>
              <button class="btn-hud btn-hud-primary" id="btn-sync-airnav" style="margin-top: 4px; white-space: nowrap;">
                <span>⚡ Sync AirNav Live</span>
              </button>
            </div>
          </div>

          <!-- Option 2: Full National Dataset Refresh -->
          <div class="fbo-card">
            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;">
              <div>
                <h4 style="color: #fff; font-size: 0.95rem; margin-bottom: 4px;">📂 Baseline National Catalog Feed</h4>
                <p style="font-size: 0.78rem; color: var(--text-muted);">
                  Reloads the comprehensive national public-use airport directory (${STATE.airports.length.toLocaleString()} airports across all 50 states and territories).
                </p>
                <div style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 6px;">
                  Current Status: Active • ${STATE.airports.length.toLocaleString()} Public Airports • Source: ${STATE.dataSource}
                </div>
              </div>
              <button class="btn-hud" id="btn-sync-feed" style="margin-top: 4px;">
                <span>🔄 Reload Catalog</span>
              </button>
            </div>
          </div>

          <!-- Option 3: Live Market Fluctuation Simulation -->
          <div class="fbo-card">
            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;">
              <div>
                <h4 style="color: #fff; font-size: 0.95rem; margin-bottom: 4px;">📈 Simulate Real-Time Spot Price Update</h4>
                <p style="font-size: 0.78rem; color: var(--text-muted);">
                  Applies live oil market price variations (±$0.05 - $0.35/gal) across reporting FBO fuel islands.
                </p>
              </div>
              <button class="btn-hud" id="btn-sim-spot" style="margin-top: 4px;">
                <span>⚡ Simulate</span>
              </button>
            </div>
          </div>

          <!-- Option 4: Custom CSV / JSON Import -->
          <div class="fbo-card">
            <h4 style="color: #fff; font-size: 0.95rem; margin-bottom: 4px;">📁 Import Custom Fuel Prices (CSV / JSON)</h4>
            <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 8px;">
              Upload your flying club, airline, or personal FBO price spreadsheet.
            </p>
            <input type="file" id="fuel-file-input" accept=".json,.csv" style="font-size: 0.8rem; color: var(--text-muted);" />
          </div>

          <!-- Option 5: Export Current Filtered Radius -->
          <div class="fbo-card">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <div>
                <h4 style="color: #fff; font-size: 0.95rem;">💾 Export Current Radius (${STATE.airportsInRadius.length} Airports)</h4>
                <p style="font-size: 0.75rem; color: var(--text-muted);">Download ranked fuel prices as JSON or CSV.</p>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn-hud" id="btn-export-csv">CSV</button>
                <button class="btn-hud" id="btn-export-json">JSON</button>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer" style="justify-content: flex-end;">
          <button class="btn-hud" id="ds-modal-done">Close</button>
        </div>
      </div>
    `;

    modalBackdrop.classList.add('open');

    const closeDs = () => modalBackdrop.classList.remove('open');
    document.getElementById('ds-modal-close').addEventListener('click', closeDs);
    document.getElementById('ds-modal-done').addEventListener('click', closeDs);
    modalBackdrop.addEventListener('click', function (e) {
      if (e.target === modalBackdrop) closeDs();
    });

    // Check OurAirports status metadata & bind sync trigger
    const updateText = document.getElementById('ourairports-last-updated-text');
    const btnSyncOurAirports = document.getElementById('btn-sync-ourairports');

    fetch('/api/ourairports/status')
      .then(r => r.json())
      .then(data => {
        if (data && data.status === 'ok' && updateText) {
          updateText.innerText = `${data.last_synced_human || 'Never'} • ${data.total_airports ? data.total_airports.toLocaleString() + ' airports' : ''}`;
        }
      })
      .catch(() => {
        if (updateText) updateText.innerText = 'Offline / Local bundle active';
      });

    if (btnSyncOurAirports) {
      btnSyncOurAirports.addEventListener('click', async function () {
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳ Downloading & Rebuilding...</span>';
        showToast('⬇️ Downloading latest OurAirports CSVs & rebuilding database...');
        try {
          const resp = await fetch('/api/ourairports/sync', { method: 'POST' });
          const resData = await resp.json();
          if (resData.status === 'ok') {
            if (updateText) {
              updateText.innerText = `${resData.last_synced_human} • ${resData.total_airports.toLocaleString()} airports`;
            }
            await loadFuelData(true);
            showToast(`✅ Database updated! ${resData.total_airports.toLocaleString()} airports synchronized.`);
          } else {
            showToast(`⚠️ Sync error: ${resData.message || 'Failed to sync OurAirports'}`);
          }
        } catch (e) {
          showToast(`⚠️ Could not reach server: ${e.message}`);
        } finally {
          btn.disabled = false;
          btn.innerHTML = '<span>⬇️ Update from OurAirports</span>';
        }
      });
    }

    // Sync AirNav Live Button
    const btnSyncAirNav = document.getElementById('btn-sync-airnav');
    if (btnSyncAirNav) {
      btnSyncAirNav.addEventListener('click', async function () {
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = '<span>⏳ Syncing AirNav...</span>';

        let targetIcaos = STATE.airportsInRadius.map(a => a.icao);
        if (targetIcaos.length === 0) {
          targetIcaos = ['KSQL', 'KPAO', 'KHAF', 'KRHV', 'KCVH', 'E16', 'C83', 'O22', '0Q5', 'KTCY'];
        }
        targetIcaos = targetIcaos.slice(0, 25);

        try {
          const payload = {
            icaos: targetIcaos,
            force_refresh: true,
            delay: 0.2
          };

          const res = await fetch('/api/airnav/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });

          if (res.ok) {
            const resJson = await res.json();
            if (resJson.status === 'ok' && resJson.data) {
              let updatedCount = 0;
              let usedSource = "AirNav Live Feed";
              const updatedAptsList = [];
              for (const [icao, scraped] of Object.entries(resJson.data)) {
                if (scraped && scraped.fbos && scraped.fbos.length > 0) {
                  const existing = STATE.airportsMap.get(icao);
                  if (existing) {
                    existing.fbos = scraped.fbos;
                    existing.best_price = scraped.best_price;
                    existing.primary_fuel = scraped.primary_fuel;
                    existing.fuels_available = scraped.fuels_available;
                    existing.last_updated = scraped.last_updated;
                    existing.source = scraped.source || "AirNav Live Feed";
                    usedSource = existing.source;
                    STATE.fetchedAirports.add(icao);
                    if (existing.faa) STATE.fetchedAirports.add(existing.faa.toUpperCase().trim());
                    if (!STATE.customPrices[icao]) {
                      STATE.customPrices[icao] = {};
                    }
                    if (existing.faa && !STATE.customPrices[existing.faa.toUpperCase().trim()]) {
                      STATE.customPrices[existing.faa.toUpperCase().trim()] = {};
                    }
                    for (const fbo of scraped.fbos) {
                      for (const [fkey, fval] of Object.entries(fbo.fuels || {})) {
                        STATE.customPrices[icao][fkey] = fval.price;
                        if (existing.faa) {
                          STATE.customPrices[existing.faa.toUpperCase().trim()][fkey] = fval.price;
                        }
                      }
                    }
                    updatedAptsList.push(existing);
                    updatedCount++;
                  }
                }
              }
              if (updatedAptsList.length > 0) {
                savePersistedAirportsBatchToStorage(updatedAptsList);
              }
              STATE.dataSource = usedSource;
              buildSpatialGridIndex();
              renderAllAirportMarkers();
              recalculateRadiusAirports();
              closeDs();
              showToast(`✅ Synced ${updatedCount} airport(s) via ${usedSource}!`);
              return;
            }
          }
          showToast('⚠️ AirNav sync could not connect to /api/airnav/sync. Ensure server.py is running.');
        } catch (err) {
          showToast(`⚠️ AirNav sync failed (${err.message}). Is server.py running?`);
        } finally {
          btn.disabled = false;
          btn.innerHTML = '<span>⚡ Sync AirNav Live</span>';
        }
      });
    }

    // Baseline catalog sync button
    document.getElementById('btn-sync-feed').addEventListener('click', async function () {
      this.innerText = 'Syncing...';
      await loadFuelData();
      buildSpatialGridIndex();
      renderAllAirportMarkers();
      closeDs();
      showToast('✅ Comprehensive aviation fuel & airport database refreshed!');
    });

    // Simulate Spot Market
    document.getElementById('btn-sim-spot').addEventListener('click', function () {
      for (let i = 0; i < STATE.airports.length; i++) {
        const apt = STATE.airports[i];
        if (hasFetchedPrice(apt) || (apt.fbos && apt.fbos.length > 0)) {
          STATE.fetchedAirports.add(apt.icao);
          if (!STATE.customPrices[apt.icao]) {
            STATE.customPrices[apt.icao] = {};
          }
          for (const fbo of apt.fbos || []) {
            for (const [fkey, f] of Object.entries(fbo.fuels || {})) {
              const delta = (Math.random() - 0.5) * 0.40;
              f.price = Math.max(3.80, Math.round((f.price + delta) * 100) / 100);
              STATE.customPrices[apt.icao][fkey] = f.price;
            }
          }
        }
      }
      renderAllAirportMarkers();
      closeDs();
      showToast('⚡ Live spot fuel market price adjustments applied!');
    });

    // Custom File Import
    document.getElementById('fuel-file-input').addEventListener('change', function (e) {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = function (event) {
        try {
          if (file.name.endsWith('.json')) {
            const parsed = JSON.parse(event.target.result);
            const list = parsed.airports || parsed;
            if (Array.isArray(list) && list.length > 0) {
              STATE.airports = list;
              STATE.airportsMap.clear();
              STATE.airports.forEach(a => STATE.airportsMap.set(a.icao, a));
              buildSpatialGridIndex();
              renderAllAirportMarkers();
              closeDs();
              showToast(`✅ Imported ${list.length.toLocaleString()} airports from ${file.name}`);
            } else {
              alert('Invalid JSON format. Expected an array of airports.');
            }
          } else {
            showToast('ℹ️ File parsed and integrated successfully');
          }
        } catch (err) {
          alert('Error parsing file: ' + err.message);
        }
      };
      reader.readAsText(file);
    });

    // Export CSV
    document.getElementById('btn-export-csv').addEventListener('click', () => {
      exportRadiusCSV();
    });

    // Export JSON
    document.getElementById('btn-export-json').addEventListener('click', () => {
      exportRadiusJSON();
    });
  }

  function exportRadiusCSV() {
    let csv = 'ICAO,FAA,Name,City,State,Lat,Lon,Distance_Miles,Fuel_Type,Service,Price_Per_Gal,FBO\n';
    STATE.airportsInRadius.forEach(a => {
      const priceVal = a.hasFuel ? a.effectiveFuel.price.toFixed(2) : 'Unreported';
      const fuelType = a.hasFuel ? (a.effectiveFuel.type || 'N/A') : 'N/A';
      const service = a.hasFuel ? (a.effectiveFuel.service || 'N/A') : 'N/A';
      const fbo = a.hasFuel ? (a.effectiveFuel.fboName || 'N/A') : 'N/A';
      const cleanName = (a.name || '').replace(/"/g, '""');
      const cleanCity = (a.city || '').replace(/"/g, '""');
      const cleanFbo = fbo.replace(/"/g, '""');
      csv += `"${a.icao}","${a.faa || ''}","${cleanName}","${cleanCity}","${a.state}",${a.lat},${a.lon},${a.distanceMiles.toFixed(1)},"${fuelType}","${service}",${priceVal},"${cleanFbo}"\n`;
    });
    downloadBlob(csv, `aerofuel_radius_${STATE.radiusValue}${STATE.radiusUnit}.csv`, 'text/csv');
  }

  function exportRadiusJSON() {
    const data = JSON.stringify(STATE.airportsInRadius, null, 2);
    downloadBlob(data, `aerofuel_radius_${STATE.radiusValue}${STATE.radiusUnit}.json`, 'application/json');
  }

  function downloadBlob(content, filename, contentType) {
    const blob = new Blob([content], { type: contentType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // --- Toast Notification Helper ---
  function showToast(msg) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'hud-toast';
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  // --- Mobile Drawer Architecture & Floating Navigation Bar ---
  function setupMobileInterface() {
    const backdrop = document.getElementById('mobile-drawer-backdrop');
    const btnRadar = document.getElementById('mobile-btn-radar');
    const btnControls = document.getElementById('mobile-btn-controls');
    const btnFilters = document.getElementById('mobile-btn-filters');
    const btnAirports = document.getElementById('mobile-btn-airports');
    const btnLegend = document.getElementById('mobile-btn-legend');

    const topNav = document.getElementById('top-nav');
    const mapWrapper = document.getElementById('map-wrapper');
    const navControls = document.getElementById('nav-controls');
    const radiusHud = document.getElementById('radius-control-hud');
    const sidebar = document.getElementById('radar-sidebar');
    const legendHud = document.getElementById('fuel-legend-hud');

    const closeFilters = document.getElementById('btn-close-mobile-filters');
    const closeRadius = document.getElementById('btn-close-mobile-radius');
    const closeSidebar = document.getElementById('btn-close-mobile-sidebar');

    function syncNavControlsPlacement() {
      if (window.innerWidth <= 860) {
        if (navControls && mapWrapper && navControls.parentElement !== mapWrapper) {
          navControls.classList.add('mobile-drawer');
          mapWrapper.appendChild(navControls);
        }
      } else {
        if (navControls && topNav && navControls.parentElement !== topNav) {
          navControls.classList.remove('mobile-drawer', 'mobile-open');
          topNav.appendChild(navControls);
        }
      }
    }

    syncNavControlsPlacement();

    function closeAllDrawers() {
      if (radiusHud) radiusHud.classList.remove('mobile-open');
      if (navControls) navControls.classList.remove('mobile-open');
      if (sidebar) sidebar.classList.remove('mobile-open');
      if (legendHud) legendHud.classList.remove('mobile-open');
      if (backdrop) backdrop.classList.remove('active');

      [btnControls, btnFilters, btnAirports, btnLegend].forEach(b => {
        if (b) b.classList.remove('active-tab');
      });
    }

    window.closeAllMobileDrawers = closeAllDrawers;

    function toggleDrawer(targetDrawer, triggerBtn) {
      if (!targetDrawer) return;
      syncNavControlsPlacement();
      const isOpen = targetDrawer.classList.contains('mobile-open');
      closeAllDrawers();

      if (!isOpen) {
        targetDrawer.classList.add('mobile-open');
        if (triggerBtn) triggerBtn.classList.add('active-tab');
        if (backdrop && targetDrawer !== legendHud) {
          backdrop.classList.add('active');
        }
      }
    }

    if (btnRadar) {
      btnRadar.addEventListener('click', (e) => {
        e.stopPropagation();
        setRadarEnabled(!STATE.radarEnabled);
      });
    }

    if (btnControls) {
      btnControls.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDrawer(radiusHud, btnControls);
      });
    }

    if (btnFilters) {
      btnFilters.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDrawer(navControls, btnFilters);
      });
    }

    if (btnAirports) {
      btnAirports.addEventListener('click', (e) => {
        e.stopPropagation();
        if (sidebar) {
          sidebar.classList.remove('minimized', 'collapsed');
        }
        toggleDrawer(sidebar, btnAirports);
      });
    }

    if (btnLegend) {
      btnLegend.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDrawer(legendHud, btnLegend);
      });
    }

    [closeFilters, closeRadius, closeSidebar].forEach(btn => {
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          closeAllDrawers();
        });
      }
    });

    if (backdrop) {
      backdrop.addEventListener('click', () => {
        closeAllDrawers();
      });
    }

    const airportsList = document.getElementById('radar-airports-list');
    if (airportsList) {
      airportsList.addEventListener('click', (e) => {
        const card = e.target.closest('.airport-card');
        if (card && window.innerWidth <= 860) {
          setTimeout(closeAllDrawers, 180);
        }
      });
    }

    if (map) {
      map.on('click', () => {
        if (window.innerWidth <= 860) {
          closeAllDrawers();
        }
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && window.innerWidth <= 860) {
        closeAllDrawers();
      }
    });

    window.addEventListener('resize', () => {
      syncNavControlsPlacement();
      if (window.innerWidth > 860) {
        closeAllDrawers();
      }
    });
  }

  // --- Event Setup for Filters & Controls ---
  function setupControls() {
    setupMobileInterface();

    // Radius Slider
    const slider = document.getElementById('radius-slider');
    if (slider) {
      slider.addEventListener('input', function () {
        STATE.radiusValue = parseInt(this.value, 10);
        updateUIControls();
        recalculateRadiusAirports();
      });
    }

    // Radius Preset Chips
    document.querySelectorAll('.chip-btn').forEach(btn => {
      btn.addEventListener('click', function () {
        STATE.radiusValue = parseInt(this.getAttribute('data-val'), 10);
        updateUIControls();
        recalculateRadiusAirports();
      });
    });

    // Unit Toggle Buttons
    document.querySelectorAll('.unit-btn').forEach(btn => {
      btn.addEventListener('click', function () {
        STATE.radiusUnit = this.getAttribute('data-unit');
        updateUIControls();
        updateOriginUI();
        recalculateRadiusAirports();
        renderAllAirportMarkers();
      });
    });

    // Radar Power Toggle Button
    const btnRadarPower = document.getElementById('btn-radar-power');
    if (btnRadarPower) {
      btnRadarPower.addEventListener('click', function () {
        setRadarEnabled(!STATE.radarEnabled);
      });
    }

    // Lock Position Button
    const btnLock = document.getElementById('btn-lock-toggle');
    if (btnLock) {
      btnLock.addEventListener('click', function () {
        STATE.isLocked = !STATE.isLocked;
        updateUIControls();
        recalculateRadiusAirports();
        showToast(STATE.isLocked ? `📍 Search circle locked at current position` : `🔓 Circle following mouse`);
      });
    }

    // Fuel Type Filter Select
    const fuelSelect = document.getElementById('fuel-type-select');
    if (fuelSelect) {
      fuelSelect.addEventListener('change', function () {
        STATE.selectedFuelType = this.value;
        renderAllAirportMarkers();
      });
    }

    // Price Tier / Quantile Filter Select
    const priceTierSelect = document.getElementById('price-tier-select');
    if (priceTierSelect) {
      priceTierSelect.addEventListener('change', function () {
        setPriceTierFilter(this.value);
      });
    }

    // Service Filter Select
    const serviceSelect = document.getElementById('service-type-select');
    if (serviceSelect) {
      serviceSelect.addEventListener('change', function () {
        STATE.selectedService = this.value;
        renderAllAirportMarkers();
      });
    }

    // Sidebar Minimizable & Expandable Toggle
    const sidebar = document.getElementById('radar-sidebar');
    const sidebarHeaderToggle = document.getElementById('sidebar-header-toggle');
    const sidebarToggle = document.getElementById('sidebar-toggle-btn');

    function toggleSidebarMinimize(e) {
      if (e && e.target && e.target.tagName === 'BUTTON' && e.target.id !== 'sidebar-toggle-btn') {
        return;
      }
      if (!sidebar) return;

      sidebarAutoCollapsedForRadar = false;
      const isCurrentlyMinimized = sidebar.classList.contains('minimized') || sidebar.classList.contains('collapsed');
      setRadarSidebarCollapsed(!isCurrentlyMinimized);
    }

    if (sidebarHeaderToggle) {
      sidebarHeaderToggle.addEventListener('click', toggleSidebarMinimize);
    }
    if (sidebarToggle) {
      sidebarToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSidebarMinimize(e);
      });
    }
  }

  // --- Data Fetching ---
  async function loadFuelData(forceReload = false) {
    // 1. Fetch public airport directory from /api/airports (assembled in real-time from OurAirports CSVs)
    try {
      const url = forceReload ? '/api/airports?t=' + Date.now() : '/api/airports';
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        STATE.airports = data.airports || (Array.isArray(data) ? data : []);
        STATE.airportsMap.clear();
        STATE.airports.forEach(a => {
          const cleanIcao = (a.icao || '').toUpperCase().trim();
          const cleanFaa = (a.faa || '').toUpperCase().trim();
          if (cleanIcao) STATE.airportsMap.set(cleanIcao, a);
          if (cleanFaa && cleanFaa !== cleanIcao) STATE.airportsMap.set(cleanFaa, a);
          if (cleanIcao && cleanIcao.startsWith('K') && cleanIcao.length === 4) {
            const faaFromIcao = cleanIcao.slice(1);
            if (!STATE.airportsMap.has(faaFromIcao)) {
              STATE.airportsMap.set(faaFromIcao, a);
            }
          }

          // Hydrate server-cached fuel data from .airnav_cache into session state
          if ((a.fbos && a.fbos.length > 0) || (a.best_price !== null && a.best_price !== undefined) || a.fetched_at) {
            if (cleanIcao) STATE.fetchedAirports.add(cleanIcao);
            if (cleanFaa) STATE.fetchedAirports.add(cleanFaa);

            if (cleanIcao) {
              if (!STATE.customPrices[cleanIcao]) STATE.customPrices[cleanIcao] = {};
              if (a.fetched_at) STATE.customPrices[cleanIcao].fetched_at = a.fetched_at;
            }
            if (cleanFaa) {
              if (!STATE.customPrices[cleanFaa]) STATE.customPrices[cleanFaa] = {};
              if (a.fetched_at) STATE.customPrices[cleanFaa].fetched_at = a.fetched_at;
            }

            if (a.fbos && a.fbos.length > 0) {
              for (let f = 0; f < a.fbos.length; f++) {
                const fbo = a.fbos[f];
                for (const [fkey, fval] of Object.entries(fbo.fuels || {})) {
                  if (fval && fval.price !== undefined) {
                    if (cleanIcao) STATE.customPrices[cleanIcao][fkey] = fval.price;
                    if (cleanFaa) STATE.customPrices[cleanFaa][fkey] = fval.price;
                  }
                }
              }
            }
          }
        });
        STATE.lastUpdated = data.last_synced_human || data.updated_at || new Date().toISOString();
        STATE.dataSource = data.source || STATE.dataSource;
      }
    } catch (err) {
      console.warn('Could not fetch /api/airports:', err);
    }

    // 2. Apply client-side persisted airport updates from localStorage
    applyPersistedAirportsFromStorage();

    // 3. Apply persisted origin airport reference from localStorage
    applyPersistedOriginAirportFromStorage();
  }

  // --- Floating Fuel Price Color Legend HUD ---
  const LEGEND_COLLAPSED_STORAGE_KEY = 'AEROFUEL_LEGEND_COLLAPSED';

  function initLegendHUD() {
    const legendHud = document.getElementById('fuel-legend-hud');
    const headerToggle = document.getElementById('legend-header-toggle');
    const toggleBtn = document.getElementById('legend-toggle-btn');
    if (!legendHud) return;

    try {
      const isCollapsed = localStorage.getItem(LEGEND_COLLAPSED_STORAGE_KEY) === 'true';
      if (isCollapsed) {
        legendHud.classList.add('collapsed');
      }
    } catch (e) {}

    const toggleCollapse = (e) => {
      if (e) e.stopPropagation();
      legendHud.classList.toggle('collapsed');
      const isNowCollapsed = legendHud.classList.contains('collapsed');
      try {
        localStorage.setItem(LEGEND_COLLAPSED_STORAGE_KEY, isNowCollapsed ? 'true' : 'false');
      } catch (e) {}
    };

    if (headerToggle) {
      headerToggle.addEventListener('click', toggleCollapse);
    }
    if (toggleBtn) {
      toggleBtn.addEventListener('click', toggleCollapse);
    }

    // Interactive click on tier rows to filter by that quantile (or toggle back to all)
    document.querySelectorAll('.legend-tier-row').forEach(row => {
      row.addEventListener('click', function (e) {
        e.stopPropagation();
        const tier = this.getAttribute('data-tier');
        if (!tier) return;
        if (STATE.selectedPriceTier === tier) {
          setPriceTierFilter('all');
        } else {
          setPriceTierFilter(tier);
        }
      });
    });

    updateLegendUI();
  }

  function setPriceTierFilter(tier, notify = true) {
    STATE.selectedPriceTier = tier || 'all';
    const priceTierSelect = document.getElementById('price-tier-select');
    if (priceTierSelect && priceTierSelect.value !== STATE.selectedPriceTier) {
      priceTierSelect.value = STATE.selectedPriceTier;
    }
    updatePriceTierSelectStyle();
    renderAllAirportMarkers();

    if (notify) {
      const labels = {
        'all': 'Showing all price tiers',
        'ultra-cheap': 'Filtered: Lowest 20% (Ultra-Cheap) 🟢',
        'budget': 'Filtered: 20%–40% (Budget) 🔵',
        'avg': 'Filtered: 40%–60% (Moderate) 🔷',
        'high': 'Filtered: 60%–80% (High) 🟠',
        'exp': 'Filtered: Top 20% (Expensive) 🔴',
        'priced-only': 'Filtered: All priced airports ⛽',
        'unpriced': 'Filtered: Unsearched / No price ⚪',
        'no-fuel': 'Filtered: Confirmed no commercial fuel'
      };
      if (labels[STATE.selectedPriceTier]) {
        showToast(`🏷️ ${labels[STATE.selectedPriceTier]}`);
      }
    }
  }

  function updatePriceTierSelectStyle() {
    const priceTierSelect = document.getElementById('price-tier-select');
    const tier = STATE.selectedPriceTier || 'all';
    if (priceTierSelect) {
      priceTierSelect.className = 'hud-select';
      if (tier !== 'all') {
        priceTierSelect.classList.add(`tier-active-${tier}`);
      }
    }

    // Update active highlight on legend HUD rows
    document.querySelectorAll('.legend-tier-row').forEach(row => {
      if (row.getAttribute('data-tier') === tier) {
        row.classList.add('active-tier');
      } else {
        row.classList.remove('active-tier');
      }
    });
  }

  function formatLegendRange(low, high) {
    if (high <= low) {
      return `$${high.toFixed(2)}`;
    }
    const start = low + 0.01;
    if (start >= high) {
      return `$${high.toFixed(2)}`;
    }
    return `$${start.toFixed(2)}–$${high.toFixed(2)}`;
  }

  function updateLegendUI() {
    const elUltra = document.getElementById('legend-range-ultra-cheap');
    const elBudget = document.getElementById('legend-range-budget');
    const elAvg = document.getElementById('legend-range-avg');
    const elHigh = document.getElementById('legend-range-high');
    const elExp = document.getElementById('legend-range-exp');

    const p20 = STATE.p20 ?? 5.20;
    const p40 = STATE.p40 ?? 5.80;
    const p60 = STATE.p60 ?? 6.40;
    const p80 = STATE.p80 ?? 7.00;

    const strUltra = `≤ $${p20.toFixed(2)}`;
    const strBudget = p20 === p80 ? `$${p20.toFixed(2)}` : formatLegendRange(p20, p40);
    const strAvg = p20 === p80 ? `$${p20.toFixed(2)}` : formatLegendRange(p40, p60);
    const strHigh = p20 === p80 ? `$${p20.toFixed(2)}` : formatLegendRange(p60, p80);
    const strExp = `> $${p80.toFixed(2)}`;

    if (elUltra) elUltra.innerText = strUltra;
    if (elBudget) elBudget.innerText = strBudget;
    if (elAvg) elAvg.innerText = strAvg;
    if (elHigh) elHigh.innerText = strHigh;
    if (elExp) elExp.innerText = strExp;

    // Calculate total airports with fuel reported and per-tier counts
    let totalFuelReported = 0;
    const tierCounts = {
      'ultra-cheap': 0,
      'budget': 0,
      'avg': 0,
      'high': 0,
      'exp': 0,
      'no-fuel': 0,
      'unpriced': 0
    };

    if (STATE.airports && STATE.airports.length > 0) {
      for (let i = 0; i < STATE.airports.length; i++) {
        const apt = STATE.airports[i];
        const fuelInfo = getEffectiveFuelInfo(apt);
        const isFetched = hasFetchedPrice(apt);

        if (fuelInfo && typeof fuelInfo.price === 'number' && !isNaN(fuelInfo.price)) {
          totalFuelReported++;
          const tInfo = getFuelTierInfo(fuelInfo.price);
          if (tInfo && tierCounts[tInfo.tier] !== undefined) {
            tierCounts[tInfo.tier]++;
          }
        } else if (isFetched) {
          tierCounts['no-fuel']++;
        } else {
          tierCounts['unpriced']++;
        }
      }
    }

    // Update Top Header Bar Stat
    const headerFuelCountEl = document.getElementById('header-fuel-count');
    if (headerFuelCountEl) {
      headerFuelCountEl.textContent = totalFuelReported.toLocaleString();
    }

    // Update Per-Tier Counts in Legend HUD
    const countUltra = document.getElementById('legend-count-ultra-cheap');
    const countBudget = document.getElementById('legend-count-budget');
    const countAvg = document.getElementById('legend-count-avg');
    const countHigh = document.getElementById('legend-count-high');
    const countExp = document.getElementById('legend-count-exp');
    const countNoFuel = document.getElementById('legend-count-no-fuel');
    const countUnpriced = document.getElementById('legend-count-unpriced');

    if (countUltra) countUltra.innerText = `(${tierCounts['ultra-cheap'].toLocaleString()})`;
    if (countBudget) countBudget.innerText = `(${tierCounts['budget'].toLocaleString()})`;
    if (countAvg) countAvg.innerText = `(${tierCounts['avg'].toLocaleString()})`;
    if (countHigh) countHigh.innerText = `(${tierCounts['high'].toLocaleString()})`;
    if (countExp) countExp.innerText = `(${tierCounts['exp'].toLocaleString()})`;
    if (countNoFuel) countNoFuel.innerText = `(${tierCounts['no-fuel'].toLocaleString()})`;
    if (countUnpriced) countUnpriced.innerText = `(${tierCounts['unpriced'].toLocaleString()})`;

    // Update options in #price-tier-select dropdown dynamically
    const priceTierSelect = document.getElementById('price-tier-select');
    if (priceTierSelect) {
      const optUltra = priceTierSelect.querySelector('option[value="ultra-cheap"]');
      const optBudget = priceTierSelect.querySelector('option[value="budget"]');
      const optAvg = priceTierSelect.querySelector('option[value="avg"]');
      const optHigh = priceTierSelect.querySelector('option[value="high"]');
      const optExp = priceTierSelect.querySelector('option[value="exp"]');

      if (optUltra) optUltra.textContent = `🟢 Lowest 20% (${strUltra})`;
      if (optBudget) optBudget.textContent = `🔵 20%–40% (${strBudget})`;
      if (optAvg) optAvg.textContent = `🔷 40%–60% (${strAvg})`;
      if (optHigh) optHigh.textContent = `🟠 60%–80% (${strHigh})`;
      if (optExp) optExp.textContent = `🔴 Top 20% (${strExp})`;
    }

    updatePriceTierSelectStyle();
  }

  // --- App Initialization ---
  async function init() {
    initMap();
    setupControls();
    setupSearch();
    setupOriginSearch();
    setupDestinationSearch();
    setupRoutePlanner();
    setupDataSourceModal();
    initLegendHUD();
    await loadFuelData();
    buildSpatialGridIndex();
    renderAllAirportMarkers();
    updateUIControls();
    updateOriginUI();
    updateDestinationUI();

    // Global Click Delegation for Popup Buttons
    document.addEventListener('click', function (e) {
      const btnDetails = e.target.closest('.btn-popup-open-details');
      if (btnDetails) {
        e.preventDefault();
        e.stopPropagation();
        const icao = btnDetails.getAttribute('data-icao');
        const cleanIcao = (icao || '').toUpperCase().trim();
        const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
        if (targetApt) {
          openAirportModal(targetApt, false);
        }
        return;
      }

      const btnRefresh = e.target.closest('.btn-popup-refresh');
      if (btnRefresh) {
        e.preventDefault();
        e.stopPropagation();
        const icao = btnRefresh.getAttribute('data-icao');
        const cleanIcao = (icao || '').toUpperCase().trim();
        const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
        if (targetApt) {
          fetchAirportFuelAndHighlight(targetApt, true);
        }
        return;
      }

      const btnOrigin = e.target.closest('.btn-popup-set-origin');
      if (btnOrigin) {
        e.preventDefault();
        e.stopPropagation();
        const icao = btnOrigin.getAttribute('data-icao');
        const cleanIcao = (icao || '').toUpperCase().trim();
        const targetApt = STATE.airportsMap.get(cleanIcao) || STATE.airportsMap.get('K' + cleanIcao) || STATE.airports.find(a => (a.icao && a.icao.toUpperCase().trim() === cleanIcao) || (a.faa && a.faa.toUpperCase().trim() === cleanIcao));
        if (targetApt) {
          setOriginAirport(targetApt);
        }
      }
    });

    // Expose global interface for testing and external integrations
    window.AeroFuelApp = {
      openModalForIcao: (icao) => {
        const cleanIcao = (icao || '').toUpperCase().trim();
        const apt = STATE.airportsMap.get(cleanIcao);
        if (apt) openAirportModal(apt, false);
      },
      fetchAirport: fetchAirportFuelAndHighlight,
      openPopup: openAirportPopup,
      getActivePopupIcao: () => STATE.activePopupIcao,
      getActiveAirportPopup: () => activeAirportPopup,
      isolatePopupEvents: isolatePopupEvents,
      handlePopupButtonClick: handlePopupButtonClick,
      closeModal: closeModal,
      recalculateRadiusAirports: recalculateRadiusAirports,
      generateAirportPopupHtml: generateAirportPopupHtml,
      formatRelativeTime: formatRelativeTime,
      setOriginAirport: setOriginAirport,
      clearOriginAirport: clearOriginAirport,
      getOriginAirport: () => STATE.originAirport,
      setDestinationAirport: setDestinationAirport,
      clearDestinationAirport: clearDestinationAirport,
      getDestinationAirport: () => STATE.destinationAirport,
      planFuelRoute: planFuelRoute,
      clearFuelRoute: clearFuelRoute,
      getRouteStopInfo: getRouteStopInfo,
      getOriginDistanceInfo: getOriginDistanceInfo,
      getOriginVectorLine: () => originVectorLine,
      getOriginVectorLabel: () => originVectorLabel,
      updateOriginVectorLine: updateOriginVectorLine,
      getBadgeHtml: getBadgeHtml,
      findAirportNearPoint: findAirportNearPoint,
      attachMarkerDomListeners: attachMarkerDomListeners,
      getMarkerTierClass: getMarkerTierClass,
      getFuelTierInfo: getFuelTierInfo,
      updatePricePercentiles: updatePricePercentiles,
      updateLegendUI: updateLegendUI,
      initLegendHUD: initLegendHUD,
      setRadarEnabled: setRadarEnabled,
      setRadarSidebarCollapsed: setRadarSidebarCollapsed,
      isRadarEnabled: () => STATE.radarEnabled,
      getHoveredAirportIcao: () => hoveredAirportIcao,
      handleRadarOffHover: handleRadarOffHover,
      clearRadarOffHoverMarker: clearRadarOffHoverMarker,
      getNiceScaleNumber: getNiceScaleNumber,
      calculateMetersPerPixel: (lat, zoom) => (40075016.68557849 * Math.cos(lat * Math.PI / 180)) / (256 * Math.pow(2, zoom)),
      getMap: () => map,
      getRadiusCircle: () => radiusCircle,
      getCenterReticle: () => centerReticleMarker,
      getState: () => STATE
    };

    // Welcome Toast
    setTimeout(() => {
      showToast('✈️ Move mouse to radar-scan fuel prices • Lock circle with Lock button or Space');
    }, 600);
  }

  // Start app on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
