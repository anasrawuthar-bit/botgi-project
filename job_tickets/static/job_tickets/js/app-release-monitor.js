(function () {
    const body = document.body;
    if (!body) {
        return;
    }

    const metaUrl = (body.dataset.botgiReleaseMetaUrl || '').trim();
    const currentVersion = (body.dataset.botgiWebVersion || '').trim();
    const pollMs = Math.max(Number(body.dataset.botgiReleasePollMs || 300000), 60000);
    const banner = document.getElementById('app-release-banner');

    if (!metaUrl || !currentVersion || !banner) {
        return;
    }

    const versionEl = banner.querySelector('[data-app-release-version]');
    const refreshButtons = banner.querySelectorAll('[data-app-refresh]');
    const dismissButtons = banner.querySelectorAll('[data-app-release-dismiss]');

    let pendingVersion = '';
    let dismissedVersion = '';
    let checkInFlight = false;

    function showBanner(nextVersion) {
        pendingVersion = nextVersion;
        if (versionEl) {
            versionEl.textContent = nextVersion;
        }
        banner.hidden = false;
    }

    function hideBanner() {
        banner.hidden = true;
    }

    async function checkForRelease() {
        if (checkInFlight) {
            return;
        }

        checkInFlight = true;
        try {
            const response = await window.fetch(metaUrl, {
                method: 'GET',
                cache: 'no-store',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            if (!response.ok) {
                return;
            }

            const payload = await response.json();
            const nextVersion = String(payload.web_version || '').trim();
            if (!nextVersion || nextVersion === currentVersion || nextVersion === dismissedVersion) {
                return;
            }

            showBanner(nextVersion);
        } catch (_error) {
            // Silently ignore transient polling/network issues.
        } finally {
            checkInFlight = false;
        }
    }

    refreshButtons.forEach((button) => {
        button.addEventListener('click', () => {
            window.location.reload();
        });
    });

    dismissButtons.forEach((button) => {
        button.addEventListener('click', () => {
            dismissedVersion = pendingVersion;
            hideBanner();
        });
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            checkForRelease();
        }
    });

    window.setTimeout(checkForRelease, Math.min(pollMs, 60000));
    window.setInterval(checkForRelease, pollMs);
})();
