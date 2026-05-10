<script lang="ts">
    import { onMount, onDestroy, untrack } from 'svelte';
    import {
        Plus,
        CassetteTape,
        HardDrive,
        Cloud,
        Trash2,
        X,
        Save,
        Globe,
        Monitor,
        RotateCw,
        PlayCircle,
        Star,
        GripVertical,
        Cpu,
        AlertCircle,
        AlertTriangle,
        ShieldAlert,
        Library,
        Minus,
        ArrowUp,
        ArrowDown,
        ArrowRight,
        MapPin,
        ShieldCheck,
        Edit3,
        Database,
        EyeOff,
        ChevronDown,
        ArrowLeftToLine,
        SkipBack,
        RotateCcw,
        AlertOctagon,
        Upload
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
    import Dialog from '$lib/components/ui/Dialog.svelte';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import { cn, formatSize } from '$lib/utils';
    import { POLL_SLOW } from '$lib/config';
    import {
        listMedia,
        createMedia,
        deleteMedia,
        triggerBackup,
        triggerAutoBackup,
        initializeMedia,
        reorderMedia,
        updateMedia,
        discoverHardware,
        ignoreHardware,
        listProviders,
        listSecrets,
        getStagingInfo,
        rewindTape,
        ejectTape,
        reinitializeTape,
        type MediaSchema,
        type StorageProviderSchema,
        type StagingInfoSchema
    } from '$lib/api';
    import { LTO_CAPACITY, PROVIDER_TEMPLATES, type LtoTapeCreateData, type OfflineHddCreateData, type CloudCreateData } from '$lib/types';
    import { dndzone } from 'svelte-dnd-action';
    import { toast } from 'svelte-sonner';
    import { beforeNavigate } from '$app/navigation';

    let mediaList = $state<MediaSchema[]>([]);
    let providersList = $state<StorageProviderSchema[]>([]);
    let discoveredAssets = $state<any[]>([]);
    let secretsList = $state<string[]>([]);
    let loading = $state(true);
    let showRegisterDialog = $state(false);
    let editingMedia = $state<MediaSchema | null>(null);
    let stagingInfo = $state<StagingInfoSchema | null>(null);

    // Tape operation state
    let tapeOperationLoading = $state<string | null>(null);
    let showReinitConfirmDialog = $state(false);
    let reinitTargetDrive = $state<any>(null);

    let activeMedia = $derived(mediaList.filter(m => m.status === 'active'));
    let fullMedia = $derived(mediaList.filter(m => m.status === 'full'));
    let unavailableMedia = $derived(mediaList.filter(m => ['failed', 'retired', 'offline'].includes(m.status)));

    // New Media Form State
    let newMedia = $state({
        media_type: 'lto_tape',
        identifier: '',
        generation: 'LTO-6',
        capacity: 2500, // 2.5 TB in GB
        _capacityFromHardware: false, // internal flag to prevent override
        _devicePath: '', // internal: device path for hardware verification
        location: 'Storage Shelf',
        location_building: '',
        location_room: '',
        location_rack: '',
        location_slot: '',
        // LTO fields
        worm: false,
        write_protected: false,
        compression: true,
        encryption_key_id: '',
        cleaning_cartridge: false,
        // HDD fields
        drive_model: '',
        device_uuid: '',
        is_ssd: false,
        mount_path: '',
        filesystem_type: '',
        connection_interface: '',
        encrypted: false,
        hdd_encryption_key_id: '',
        // Cloud fields
        provider_template: 'aws',
        endpoint_url: 's3.amazonaws.com',
        region: 'us-east-1',
        bucket_name: '',
        access_key_id: '',
        secret_access_key_name: '',
        path_style_access: false,
        storage_class: '',
        max_part_size_mb: 5000,
        obfuscate_filenames: false,
        encryption_secret_name: '',
        // OAuth provider fields (google_drive / dropbox)
        credential_key: '',
        oauth_email: '',
        oauth_state: '',
        oauth_polling: false,
        root_folder: ''
    });

    let oauthPopup: Window | null = null;
    let oauthPollTimer: ReturnType<typeof setInterval> | null = null;

    async function startOAuth(provider: 'google_drive' | 'dropbox') {
        try {
            const res = await fetch(`/oauth/start?provider=${provider}`);
            if (!res.ok) {
                const err = await res.json();
                toast.error(err.detail || 'OAuth start failed');
                return;
            }
            const { auth_url, state } = await res.json();
            newMedia.oauth_state = state;
            newMedia.oauth_polling = true;
            newMedia.oauth_email = '';
            newMedia.credential_key = '';

            oauthPopup = window.open(auth_url, 'tapehoard_oauth', 'width=600,height=700,left=300,top=100');

            // Listen for postMessage from the callback page
            const handleMessage = (event: MessageEvent) => {
                if (event.data?.tapehoard_oauth) {
                    const { credential_key, email, error } = event.data.tapehoard_oauth;
                    if (error) {
                        toast.error(`OAuth error: ${error}`);
                        newMedia.oauth_polling = false;
                    } else {
                        newMedia.credential_key = credential_key;
                        newMedia.oauth_email = email;
                        newMedia.oauth_polling = false;
                        toast.success(`Connected as ${email}`);
                    }
                    window.removeEventListener('message', handleMessage);
                    if (oauthPollTimer) { clearInterval(oauthPollTimer); oauthPollTimer = null; }
                }
            };
            window.addEventListener('message', handleMessage);

            // Fallback polling in case postMessage is blocked
            oauthPollTimer = setInterval(async () => {
                if (!newMedia.oauth_polling) { clearInterval(oauthPollTimer!); oauthPollTimer = null; return; }
                try {
                    const pr = await fetch(`/oauth/poll/${state}`);
                    if (!pr.ok) return;
                    const pd = await pr.json();
                    if (pd.status === 'connected') {
                        newMedia.credential_key = pd.credential_key;
                        newMedia.oauth_email = pd.email;
                        newMedia.oauth_polling = false;
                        toast.success(`Connected as ${pd.email}`);
                        window.removeEventListener('message', handleMessage);
                        clearInterval(oauthPollTimer!); oauthPollTimer = null;
                    } else if (pd.status === 'error') {
                        toast.error(`OAuth error: ${pd.error}`);
                        newMedia.oauth_polling = false;
                        window.removeEventListener('message', handleMessage);
                        clearInterval(oauthPollTimer!); oauthPollTimer = null;
                    }
                } catch (_) {}
            }, 2000);
        } catch (e) {
            toast.error('Failed to start OAuth flow');
        }
    }

    // Provider template change handler
    function handleProviderTemplateChange(template: string) {
        newMedia.provider_template = template;
        const defaults = PROVIDER_TEMPLATES[template];
        if (defaults) {
            newMedia.endpoint_url = defaults.endpoint;
            newMedia.region = defaults.region;
        }
    }

    // LTO Generation change handler (auto-populate capacity only if not from hardware)
    function handleGenerationChange(gen: string) {
        newMedia.generation = gen;
        if (LTO_CAPACITY[gen] && !newMedia._capacityFromHardware) {
            newMedia.capacity = LTO_CAPACITY[gen];
        }
    }

    const activeProvider = $derived(
        providersList.find(p => p.provider_id === newMedia.media_type)
    );

    // Media type change handler
    $effect(() => {
        // Track provider identity changes to reset form
        const _id = activeProvider?.provider_id;
        // Reset form when media type changes
        if (activeProvider && newMedia.media_type !== 'lto_tape') {
            untrack(() => {
                newMedia.generation = '';
                newMedia.capacity = 0;
            });
        } else if (activeProvider && newMedia.media_type === 'lto_tape' && newMedia.capacity === 0) {
            untrack(() => {
                newMedia.generation = 'LTO-6';
                newMedia.capacity = LTO_CAPACITY['LTO-6'];
            });
        }
    });

    // Track "dirty" state for dialogs
    const isFormDirty = $derived(
        (showRegisterDialog && (newMedia.identifier !== '')) ||
        (editingMedia !== null)
    );

    beforeNavigate((navigation) => {
        if (isFormDirty) {
            if (!confirm("You have a registration or edit dialog open. Your changes will be lost. Leave anyway?")) {
                navigation.cancel();
            }
        }
    });

    $effect(() => {
        const handleBeforeUnload = (e: BeforeUnloadEvent) => {
            if (isFormDirty) {
                e.preventDefault();
                e.returnValue = "";
            }
        };
        window.addEventListener('beforeunload', handleBeforeUnload);
        return () => window.removeEventListener('beforeunload', handleBeforeUnload);
    });

    let pollInterval: any;

    const onlineDevicePaths = $derived(
        new Set(
            mediaList
                .filter(m => m.is_online && (m.media_type === 'lto_tape' || m.media_type === 'tape') && m.identifier)
                .map(m => m.identifier)
        )
    );

    const filteredDiscoveredAssets = $derived(
        discoveredAssets.filter(asset => {
            // Hide if backend already thinks it's registered
            if (asset.is_registered) return false;
            // Hide if its device_path is currently claimed by an online registered tape
            if (asset.type === 'tape' && onlineDevicePaths.has(asset.device_path)) return false;
            return true;
        })
    );

    async function loadMedia(silent = false, refresh = false) {
        if (!silent) loading = true;
        try {
            const [mediaRes, hardwareRes] = await Promise.all([
                listMedia({ query: { refresh } }),
                discoverHardware()
            ]);
            if (mediaRes.data) {
                // Implement client-side Last Known Good (LKG) caching for hardware status
                mediaList = mediaRes.data.map(newMedia => {
                    const oldMedia = mediaList.find(m => m.id === newMedia.id);
                    if (oldMedia && oldMedia.live_info && newMedia.live_info) {
                        const newInfo = newMedia.live_info as any;
                        const oldInfo = oldMedia.live_info as any;
                        // If new info is empty (due to a busy drive), preserve the old info
                        if (Object.keys(newInfo.tape || {}).length === 0 && Object.keys(oldInfo.tape || {}).length > 0) {
                            newInfo.tape = oldInfo.tape;
                        }
                        if (Object.keys(newInfo.drive || {}).length === 0 && Object.keys(oldInfo.drive || {}).length > 0) {
                            newInfo.drive = oldInfo.drive;
                        }
                    }
                    return newMedia;
                });
            }
            if (hardwareRes.data) {
                discoveredAssets = (hardwareRes.data as any[]).map(newAsset => {
                    const oldAsset = discoveredAssets.find(a => a.device_path === newAsset.device_path);
                    if (oldAsset && oldAsset.hardware_info && newAsset.hardware_info) {
                        // null = backend confirmed no tape loaded; {} = drive busy, cache may be empty.
                        // Only preserve old tape info for the {} case, never for null.
                        if (newAsset.hardware_info.tape !== null && Object.keys(newAsset.hardware_info.tape || {}).length === 0 && Object.keys(oldAsset.hardware_info.tape || {}).length > 0) {
                            newAsset.hardware_info.tape = oldAsset.hardware_info.tape;
                        }
                        if (Object.keys(newAsset.hardware_info.drive || {}).length === 0 && Object.keys(oldAsset.hardware_info.drive || {}).length > 0) {
                            newAsset.hardware_info.drive = oldAsset.hardware_info.drive;
                        }
                    }
                    return newAsset;
                });
            }
        } catch (error) {
            if (!silent) toast.error("Failed to load inventory details");
        } finally {
            if (!silent) loading = false;
        }
    }

    async function pollHardware() {
        try {
            const res = await discoverHardware();
            if (!res.data) return;

            const prevPaths = new Set(discoveredAssets.map(a => a.device_path));
            let hasNew = false;

            discoveredAssets = (res.data as any[]).map(newAsset => {
                if (!prevPaths.has(newAsset.device_path)) {
                    hasNew = true;
                }
                const oldAsset = discoveredAssets.find(a => a.device_path === newAsset.device_path);
                if (oldAsset && oldAsset.hardware_info && newAsset.hardware_info) {
                    // null = backend confirmed no tape loaded; {} = drive busy, cache may be empty.
                    // Only preserve old tape info for the {} case, never for null.
                    if (newAsset.hardware_info.tape !== null && Object.keys(newAsset.hardware_info.tape || {}).length === 0 && Object.keys(oldAsset.hardware_info.tape || {}).length > 0) {
                        newAsset.hardware_info.tape = oldAsset.hardware_info.tape;
                    }
                    if (Object.keys(newAsset.hardware_info.drive || {}).length === 0 && Object.keys(oldAsset.hardware_info.drive || {}).length > 0) {
                        newAsset.hardware_info.drive = oldAsset.hardware_info.drive;
                    }
                }
                return newAsset;
            });

            if (hasNew) {
                loadMedia(true, true);
            }
        } catch (error) {
            console.error("Hardware discovery failed:", error);
        }
    }

    let prevOnlineCount = $state(0);

    $effect(() => {
        const currentOnlineCount = mediaList.filter(m => m.is_online).length;
        if (currentOnlineCount > prevOnlineCount) {
            // New hardware detected online, trigger a forced refresh to identify it immediately
            loadMedia(true, true);
        }
        prevOnlineCount = currentOnlineCount;
    });

    async function loadSecrets() {
        try {
            const res = await listSecrets();
            if (res.data) secretsList = res.data as string[];
        } catch (error) {
            console.error("Failed to load secrets:", error);
        }
    }

    async function loadStagingInfo() {
        try {
            const res = await getStagingInfo();
            if (res.data) stagingInfo = res.data;
        } catch (error) {
            console.error("Failed to load staging info:", error);
        }
    }

    onMount(async () => {
        // Initial load (non-silent and forced refresh to show live hardware status immediately)
        loadMedia(false, true);
        loadSecrets();
        loadStagingInfo();

        try {
            const res = await listProviders();
            if (res.data) providersList = res.data;
        } catch (error) {
            console.error("Failed to load storage providers:", error);
        }

        pollInterval = setInterval(() => {
            pollHardware();
            loadStagingInfo();
            // Refresh media list (DB-only, no hardware query) so bytes_used
            // stays current after backup jobs complete.
            loadMedia(true, false);
        }, POLL_SLOW);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    $effect(() => {
        const needsReg = mediaList.find(m => m.is_online && m.needs_registration);
        if (needsReg) {
            toast.info(`New media detected: ${needsReg.identifier}. Please register or initialize it.`, {
                action: {
                    label: 'Register',
                    onClick: () => {
                        newMedia.media_type = needsReg.media_type;
                        newMedia.identifier = needsReg.identifier;
                        showRegisterDialog = true;
                    }
                }
            });
        }
    });

    function handleDndConsider(e: CustomEvent) {
        const activeItems = e.detail.items;
        const inactiveItems = mediaList.filter(m => m.status !== 'active' || (m.capacity > 0 && (m.bytes_used / m.capacity) >= 0.98));
        mediaList = [...activeItems, ...inactiveItems];
    }

    async function handleDndFinalize(e: CustomEvent) {
        const activeItems = e.detail.items;
        const inactiveItems = mediaList.filter(m => m.status !== 'active' || (m.capacity > 0 && (m.bytes_used / m.capacity) >= 0.98));
        mediaList = [...activeItems, ...inactiveItems];

        try {
            await reorderMedia({
                body: { media_ids: mediaList.map(m => m.id) },
                throwOnError: true
            });
            toast.success("Archival priority updated");
        } catch (error) {
            toast.error("Failed to save media order");
            loadMedia();
        }
    }

    async function handleInitialize(mediaId: number, identifier: string, force = false) {
        if (!force && !confirm(`Are you sure you want to initialize ${identifier}? This will wipe existing data on the media.`)) return;

        try {
            toast.info(`Initializing ${identifier}...`);
            await initializeMedia({
                path: { media_id: mediaId },
                query: { force },
                throwOnError: true
            });
            toast.success(`${identifier} initialized successfully`);
            loadMedia();
        } catch (error: any) {
            if (error.status === 409) {
                if (confirm(error.body?.detail || "Media already has backups. Overwrite?")) {
                    handleInitialize(mediaId, identifier, true);
                }
            } else {
                toast.error(error.body?.detail || "Failed to initialize media");
            }
        }
    }

    async function handleStartBackup(mediaId: number, identifier: string) {
        try {
            await triggerBackup({
                path: { media_id: mediaId },
                throwOnError: true
            });
            toast.success(`Archival job initiated for ${identifier}`);
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start archival");
        }
    }

    async function handleAutoArchive() {
        try {
            await triggerAutoBackup({
                throwOnError: true
            });
            toast.success("Auto-archival job initiated for all active media");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start auto-archival");
        }
    }

    async function handleRegister() {
        if (!newMedia.identifier) {
            toast.error("Identifier is required");
            return;
        }

        // Build type-specific payload
        let payload: any = {
            media_type: newMedia.media_type,
            identifier: newMedia.identifier,
            capacity: newMedia.capacity * 1000 * 1000 * 1000, // Convert GB to bytes
            location: newMedia.location,
            location_building: newMedia.location_building || undefined,
            location_room: newMedia.location_room || undefined,
            location_rack: newMedia.location_rack || undefined,
            location_slot: newMedia.location_slot || undefined,
        };

        if (newMedia.media_type === 'lto_tape') {
            payload.generation = newMedia.generation;
            payload.worm = newMedia.worm;
            payload.write_protected = newMedia.write_protected;
            payload.compression = newMedia.compression;
            payload.encryption_key_id = newMedia.encryption_key_id || undefined;
            payload.cleaning_cartridge = newMedia.cleaning_cartridge;
            payload.encryption_secret_name = newMedia.encryption_secret_name || undefined;
            if (newMedia._devicePath) {
                payload.device_path = newMedia._devicePath;
            }
        } else if (newMedia.media_type === 'local_hdd') {
            payload.drive_model = newMedia.drive_model || undefined;
            payload.device_uuid = newMedia.device_uuid || undefined;
            payload.is_ssd = newMedia.is_ssd;
            payload.mount_path = newMedia.mount_path || undefined;
            payload.filesystem_type = newMedia.filesystem_type || undefined;
            payload.connection_interface = newMedia.connection_interface || undefined;
            payload.encrypted = newMedia.encrypted;
            payload.encryption_key_id = newMedia.hdd_encryption_key_id || undefined;
            payload.encryption_secret_name = newMedia.encryption_secret_name || undefined;
        } else if (newMedia.media_type === 's3_compat') {
            payload.provider_template = newMedia.provider_template;
            payload.endpoint_url = newMedia.endpoint_url;
            payload.region = newMedia.region;
            payload.bucket_name = newMedia.bucket_name;
            payload.access_key_id = newMedia.access_key_id;
            payload.secret_access_key_name = newMedia.secret_access_key_name || undefined;
            payload.path_style_access = newMedia.path_style_access;
            payload.storage_class = newMedia.storage_class || undefined;
            payload.max_part_size_mb = newMedia.max_part_size_mb;
            payload.obfuscate_filenames = newMedia.obfuscate_filenames;
            payload.encryption_secret_name = newMedia.encryption_secret_name || undefined;
        } else if (newMedia.media_type === 'google_drive') {
            if (!newMedia.credential_key) { toast.error('Connect a Google account first'); return; }
            payload.credential_key = newMedia.credential_key;
            payload.encryption_secret_name = newMedia.encryption_secret_name || undefined;
            payload.obfuscate_filenames = newMedia.obfuscate_filenames;
        } else if (newMedia.media_type === 'dropbox') {
            if (!newMedia.credential_key) { toast.error('Connect a Dropbox account first'); return; }
            payload.credential_key = newMedia.credential_key;
            if (newMedia.root_folder) payload.root_folder = newMedia.root_folder;
            payload.encryption_secret_name = newMedia.encryption_secret_name || undefined;
            payload.obfuscate_filenames = newMedia.obfuscate_filenames;
        }

        try {
            await createMedia({
                body: payload,
                throwOnError: true
            });
            toast.success(`${newMedia.identifier} registered in inventory`);
            showRegisterDialog = false;
            loadMedia();
        } catch (error) {
            toast.error("Failed to register media");
        }
    }

    function openEdit(media: MediaSchema) {
        editingMedia = JSON.parse(JSON.stringify(media)) as MediaSchema;
        // Convert capacity from bytes to GB for editing, always floor
        editingMedia.capacity = Math.floor(editingMedia.capacity / (1000 * 1000 * 1000));
        // Ensure all fields exist for type-specific editing
        if (editingMedia.media_type === 'lto_tape') {
            editingMedia.encryption_key_id = editingMedia.encryption_key_id || '';
        } else if (editingMedia.media_type === 'local_hdd') {
            editingMedia.drive_model = editingMedia.drive_model || '';
            editingMedia.device_uuid = editingMedia.device_uuid || '';
            editingMedia.mount_path = editingMedia.mount_path || '';
            editingMedia.filesystem_type = editingMedia.filesystem_type || '';
            editingMedia.connection_interface = editingMedia.connection_interface || '';
            editingMedia.encryption_key_id = editingMedia.encryption_key_id || '';
        } else if (editingMedia.media_type === 's3_compat') {
            editingMedia.endpoint_url = editingMedia.endpoint_url || '';
            editingMedia.region = editingMedia.region || '';
            editingMedia.bucket_name = editingMedia.bucket_name || '';
            editingMedia.access_key_id = editingMedia.access_key_id || '';
            editingMedia.storage_class = editingMedia.storage_class || '';
            editingMedia.path_style_access = editingMedia.path_style_access ?? false;
            editingMedia.obfuscate_filenames = editingMedia.obfuscate_filenames ?? false;
            editingMedia.secret_access_key_name = editingMedia.secret_access_key_name || '';
            editingMedia.encryption_secret_name = editingMedia.encryption_secret_name || '';
        }
    }

    async function handleUpdate() {
        if (!editingMedia) return;

        const capacityBytes = editingMedia.capacity * 1000 * 1000 * 1000;
        if (capacityBytes < editingMedia.bytes_used) {
            toast.error(`Capacity cannot be less than utilized space (${formatSize(editingMedia.bytes_used)})`);
            return;
        }

        // Build update payload with type-specific fields
        let payload: any = {
            location: editingMedia.location || undefined,
            location_building: editingMedia.location_building || undefined,
            location_room: editingMedia.location_room || undefined,
            location_rack: editingMedia.location_rack || undefined,
            location_slot: editingMedia.location_slot || undefined,
            status: editingMedia.status,
            capacity: capacityBytes,
        };

        // LTO fields
        if (editingMedia.media_type === 'lto_tape') {
            payload.compression = editingMedia.compression;
            payload.worm = editingMedia.worm;
            payload.write_protected = editingMedia.write_protected;
            payload.cleaning_cartridge = editingMedia.cleaning_cartridge;
            payload.encryption_key_id = editingMedia.encryption_key_id || undefined;
            payload.encryption_secret_name = editingMedia.encryption_secret_name || undefined;
        }
        // HDD fields
        else if (editingMedia.media_type === 'local_hdd') {
            payload.drive_model = editingMedia.drive_model || undefined;
            payload.device_uuid = editingMedia.device_uuid || undefined;
            payload.is_ssd = editingMedia.is_ssd;
            payload.encrypted = editingMedia.encrypted;
            payload.encryption_key_id = editingMedia.encryption_key_id || undefined;
            payload.encryption_secret_name = editingMedia.encryption_secret_name || undefined;
        }
        // Cloud fields
        else if (editingMedia.media_type === 's3_compat') {
            payload.endpoint_url = editingMedia.endpoint_url || undefined;
            payload.region = editingMedia.region || undefined;
            payload.bucket_name = editingMedia.bucket_name || undefined;
            payload.access_key_id = editingMedia.access_key_id || undefined;
            payload.secret_access_key_name = editingMedia.secret_access_key_name || undefined;
            payload.path_style_access = editingMedia.path_style_access;
            payload.obfuscate_filenames = editingMedia.obfuscate_filenames;
            payload.storage_class = editingMedia.storage_class || undefined;
            payload.encryption_secret_name = editingMedia.encryption_secret_name || undefined;
        }

        // Remove undefined values
        Object.keys(payload).forEach(key => {
            if (payload[key] === undefined) {
                delete payload[key];
            }
        });

        try {
            await updateMedia({
                path: { media_id: editingMedia.id },
                body: payload,
                throwOnError: true
            });
            toast.success("Media configuration updated");
            editingMedia = null;
            loadMedia();
        } catch (error: any) {
            const detail = error?.body?.detail || "Failed to update media";
            toast.error(detail);
        }
    }

    async function handleIgnoreAsset(identifier: string) {
        try {
            await ignoreHardware({
                body: { identifier }
            });
            loadMedia();
        } catch (error) {
            toast.error("Failed to ignore asset");
        }
    }

    async function handleTapeRewind(devicePath: string) {
        tapeOperationLoading = `rewind-${devicePath}`;
        try {
            await rewindTape({
                body: { device_path: devicePath }
            });
            toast.success("Tape rewound to BOT");
            // Refresh to get updated file number
            await loadMedia(true, true);
        } catch (error: any) {
            const msg = error?.response?.data?.detail || error?.message || "Unknown error";
            toast.error(`Rewind failed: ${msg}`);
        } finally {
            tapeOperationLoading = null;
        }
    }

    async function handleTapeEject(devicePath: string) {
        tapeOperationLoading = `eject-${devicePath}`;
        try {
            await ejectTape({
                body: { device_path: devicePath }
            });
            toast.success("Tape ejected");
            // Refresh to show tape as unloaded
            await loadMedia(true, true);
        } catch (error: any) {
            const msg = error?.response?.data?.detail || error?.message || "Unknown error";
            toast.error(`Eject failed: ${msg}`);
        } finally {
            tapeOperationLoading = null;
        }
    }

    function openReinitConfirm(drive: any) {
        reinitTargetDrive = drive;
        showReinitConfirmDialog = true;
    }

    async function handleTapeReinitialize(secureErase = false) {
        if (!reinitTargetDrive) return;
        const devicePath = reinitTargetDrive.device_path;
        tapeOperationLoading = `reinit-${devicePath}`;
        showReinitConfirmDialog = false;
        try {
            await reinitializeTape({
                body: { device_path: devicePath, secure_erase: secureErase }
            });
            toast.success(secureErase
                ? "Tape securely erased. Use 'Initialize Media' to write a new label."
                : "Tape cleared. Use 'Initialize Media' to write a new label."
            );
            await loadMedia(true, true);
        } catch (error: any) {
            const msg = error?.response?.data?.detail || error?.message || "Unknown error";
            toast.error(`Re-initialize failed: ${msg}`);
        } finally {
            tapeOperationLoading = null;
            reinitTargetDrive = null;
        }
    }

    async function handleDelete(mediaId: number) {
        if (!confirm("Remove this media from inventory? Data on the physical media will remain, but TapeHoard will lose its index association.")) return;
        try {
            await deleteMedia({
                path: { media_id: mediaId }
            });
            toast.success("Media removed from inventory");
            loadMedia();
        } catch (error) {
            toast.error("Failed to delete media");
        }
    }

</script>

{#snippet ConfigIcon(type: string)}
    {#if type === 'lto_tape' || type === 'tape'}<CassetteTape size={24} />
    {:else if type === 'local_hdd' || type === 'hdd'}<HardDrive size={24} />
    {:else}<Cloud size={24} />
    {/if}
{/snippet}

{#snippet mediaRow(media: MediaSchema)}
    <td class="px-6 py-3">
        {#if media.status === 'active' && mediaList.filter(m => m.status === 'active')[0]?.id === media.id}
             <div class="flex items-center gap-2">
                <Star size={12} class="text-yellow-500" fill="currentColor" />
                <span class="text-[10px] font-semibold text-yellow-500/80">Priority 1</span>
            </div>
        {:else}
            <span class="text-[10px] font-medium text-text-secondary opacity-20 mono">#{media.priority_index}</span>
        {/if}
    </td>
    <td class="px-2 py-3">
        <div class="flex justify-center">
            {#if media.is_online}
                {#if media.is_identified}
                    <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.6)]" title="Hardware verified & online"></div>
                {:else}
                    <div class="w-2 h-2 rounded-full bg-orange-500 shadow-[0_0_10px_rgba(249,115,22,0.6)] animate-pulse" title="Hardware present but uninitialized"></div>
                {/if}
            {:else}
                <div class="w-2 h-2 rounded-full bg-text-secondary/10 border border-text-secondary/20" title="Offline"></div>
            {/if}
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex flex-col">
            <span class="text-sm font-semibold text-text-primary truncate">{media.identifier}</span>
            <div class="mt-0.5 flex flex-col gap-0.5">
                {#if media.media_type === 'local_hdd' && media.mount_path}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[10px] mono truncate">
                        <Monitor size={10} /> {media.mount_path}
                    </div>
                {:else if media.media_type === 's3_compat' && media.bucket_name}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[10px] mono truncate">
                        <Globe size={10} /> {media.bucket_name}
                    </div>
                {:else if media.media_type === 'lto_tape' && media.generation}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[10px] mono truncate">
                        <CassetteTape size={10} /> {media.generation}
                    </div>
                {/if}
                <div class="flex flex-wrap gap-1 mt-0.5">
                    {#if media.status === 'failed'}
                        <StatusBadge variant="error">Hardware failure</StatusBadge>
                    {:else if media.status === 'retired'}
                        <StatusBadge variant="neutral">Retired</StatusBadge>
                    {/if}

                    {#if media.encryption_key_id || media.encrypted}
                        <StatusBadge variant="info">
                            <ShieldCheck size={8} /> Encrypted
                        </StatusBadge>
                    {/if}
                    {#if media.worm}
                        <StatusBadge variant="warning">WORM</StatusBadge>
                    {/if}
                    {#if media.cleaning_cartridge}
                        <StatusBadge variant="neutral">Cleaning</StatusBadge>
                    {/if}
                </div>
            </div>
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex flex-col">
            <span class="text-xs font-medium text-text-secondary">{media.media_type}</span>
            <div class="flex items-center gap-2 mt-0.5">
                <span class="text-[10px] font-medium text-text-secondary/40">{media.generation || media.generation_tier || 'Generic'}</span>
                {#if media.media_type === 'local_hdd' && media.device_uuid}
                    <span class="text-[10px] mono text-text-secondary/30 truncate max-w-[80px]">{media.device_uuid}</span>
                {/if}
                {#if media.media_type === 'local_hdd' && media.drive_model}
                    <span class="text-[10px] text-text-secondary/30 truncate max-w-[100px]">{media.drive_model}</span>
                {/if}
            </div>
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex items-center gap-1.5 text-text-secondary">
            <MapPin size={12} class="opacity-40" />
            <span class="text-xs font-medium">{media.location_building ? [media.location_building, media.location_room, media.location_rack, media.location_slot].filter(Boolean).join(' / ') : (media.location || 'Unknown')}</span>
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex flex-col w-32 gap-1">
            <div class="flex justify-between items-end text-xs">
                <span class="font-medium text-text-primary mono">{formatSize(media.bytes_used)}</span>
                <span class="text-text-secondary opacity-40 font-medium">{Math.round((media.bytes_used / (media.capacity || 1)) * 100)}%</span>
            </div>
            <ProgressBar value={Math.round((media.bytes_used / (media.capacity || 1)) * 100)} size="sm" />
            <span class="text-[9px] text-text-secondary opacity-30 font-medium text-right">CAP: {formatSize(media.capacity)}</span>
        </div>
    </td>
    <td class="px-6 py-3 text-right">
        <div class="flex justify-end gap-1">
            {#if media.is_online}
                {#if !media.is_identified}
                    <Button variant="outline" size="sm" class="h-7 text-[10px] border-orange-500/30 text-orange-400 hover:bg-orange-500/10" onclick={() => handleInitialize(media.id, media.identifier)}>Initialize</Button>
                {:else if media.status === 'active' && (media.bytes_used / (media.capacity || 1)) < 0.98}
                    <Button variant="default" size="sm" class="h-7 text-[10px] bg-blue-600 hover:bg-blue-500" onclick={() => handleStartBackup(media.id, media.identifier)}>Archive</Button>
                {/if}
            {/if}
            <Button variant="ghost" size="icon" class="h-7 w-7 text-text-secondary hover:text-text-primary hover:bg-white/5" onclick={() => openEdit(media)}><Edit3 size={14} /></Button>
            <Button variant="ghost" size="icon" class="h-7 w-7 text-text-secondary hover:text-error-color hover:bg-error-color/10" onclick={() => handleDelete(media.id)}><Trash2 size={16} /></Button>
        </div>
    </td>
{/snippet}

<svelte:head>
    <title>Media Inventory - TapeHoard</title>
</svelte:head>

<div class="flex flex-col h-full gap-6 animate-in fade-in duration-700 overflow-y-auto p-1">
    <PageHeader
        title="Physical inventory"
        description="Fleet management & hardware status"
        icon={Library}
    >
        {#snippet actions()}
            {#if mediaList.some(m => m.status === 'active' && (m.bytes_used / m.capacity) < 0.98)}
                <Button variant="default" class="bg-blue-600 hover:bg-blue-700" onclick={handleAutoArchive}>
                    <PlayCircle size={16} class="mr-2" /> Auto archive
                </Button>
            {/if}
            <Button variant="default" onclick={() => showRegisterDialog = true}>
                <Plus size={16} class="mr-2" /> Register media
            </Button>
        {/snippet}
    </PageHeader>

    <div class="space-y-12">
        <!-- DISCOVERED HARDWARE SECTION -->
        {#if filteredDiscoveredAssets.length > 0}
            <section class="space-y-4">
                <SectionHeader title="Discovered unregistered drives" icon={Cpu} iconColor="text-action-color" />

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {#each filteredDiscoveredAssets as asset}
                        <Card class="p-4 bg-bg-secondary border-dashed border-2 border-border-color hover:border-action-color/50 transition-all group">
                            <div class="flex items-start gap-4">
                                <div class="p-2.5 bg-action-color/10 rounded-xl text-action-color border border-action-color/20">
                                    {@render ConfigIcon(asset.type === 'tape' ? 'lto_tape' : 'local_hdd')}
                                </div>
                                <div class="flex-1 min-w-0">
                                    <h3 class="text-sm font-bold text-text-primary truncate">{asset.identifier}</h3>
                                    <div class="flex items-center gap-1.5 mt-0.5 opacity-60">
                                        <Cpu size={10} class="text-action-color" />
                                        <span class="text-xs text-text-secondary truncate mono">
                                            {#if asset.type === 'tape'}
                                                {asset.device_path}
                                            {:else}
                                                {asset.mount_path}
                                            {/if}
                                        </span>
                                    </div>

                                    {#if asset.type === 'tape' && asset.hardware_info}
                                        <div class="mt-3 space-y-1.5 border-t border-border-color/30 pt-3">
                                            {#if asset.hardware_info.drive}
                                                <div class="text-[10px] font-medium text-blue-400/80">
                                                    Drive: {asset.hardware_info.drive.vendor} {asset.hardware_info.drive.model} ({asset.hardware_info.drive.firmware})
                                                </div>
                                            {/if}
                                            {#if asset.hardware_info.tape}
                                                <div class="flex flex-wrap gap-1">
                                                    {#if asset.hardware_info.tape.barcode}
                                                        <span class="text-[9px] font-medium bg-white/5 px-1.5 py-0.5 rounded border border-white/10 text-text-secondary">BC: {asset.hardware_info.tape.barcode}</span>
                                                    {/if}
                                                    {#if asset.hardware_info.tape.serial}
                                                        <span class="text-[9px] font-medium bg-blue-500/10 px-1 rounded border border-blue-500/20 text-blue-400">SN: {asset.hardware_info.tape.serial}</span>
                                                    {/if}
                                                    <span class="text-[9px] font-medium bg-white/5 px-1.5 py-0.5 rounded border border-white/10 text-text-secondary">{asset.hardware_info.tape.generation_label || asset.hardware_info.tape.generation}</span>
                                                </div>
                                            {/if}
                                        </div>
                                    {/if}

                                        <div class="mt-4 flex gap-2">
                                            <Button variant="default" size="sm" class="h-8 text-xs flex-1" onclick={() => {
                                                newMedia.media_type = asset.type === 'tape' ? 'lto_tape' : 'local_hdd';
                                                newMedia.identifier = asset.identifier === 'Unrecognized Disk' ? '' : asset.identifier;

                                                // Pre-fill based on asset type
                                                if (asset.type === 'hdd') {
                                                    newMedia.mount_path = asset.mount_path || '';
                                                    newMedia.device_uuid = asset.device_uuid || '';
                                                    if (asset.capacity_bytes) {
                                                        newMedia.capacity = asset.capacity_bytes;
                                                    }
                                                } else if (asset.type === 'tape') {
                                                    if (asset.hardware_info?.tape?.serial) {
                                                        newMedia.identifier = asset.hardware_info.tape.serial;
                                                    }
                                                    if (asset.hardware_info?.tape?.barcode) {
                                                        newMedia.identifier = asset.hardware_info.tape.barcode;
                                                    }
                                                    if (asset.hardware_info?.tape?.max_capacity_mib) {
                                                        // Convert MiB to GB (base-10), always FLOOR to avoid
                                                        // over-reporting physical capacity.
                                                        newMedia.capacity = Math.floor(asset.hardware_info.tape.max_capacity_mib * 1024 * 1024 / (1000 * 1000 * 1000));
                                                        newMedia._capacityFromHardware = true;
                                                    }
                                                    if (asset.hardware_info?.tape?.generation_label) {
                                                        newMedia.generation = asset.hardware_info.tape.generation_label;
                                                    }
                                                    // Pass device path so backend can verify against hardware
                                                    newMedia._devicePath = asset.device_path || '';
                                                }
                                                showRegisterDialog = true;
                                            }}>Add media</Button>
                                        <Button variant="outline" size="sm" class="h-8 text-xs border-border-color/60 text-text-secondary hover:bg-white/5" onclick={() => handleIgnoreAsset(asset.identifier)}>Ignore</Button>
                                    </div>
                                </div>
                            </div>
                        </Card>
                    {/each}
                </div>
            </section>
        {/if}

        <!-- INVENTORY SECTION -->
        <section class="space-y-12">
            <!-- Hardware Status - Shows one card per tape device -->
            {#if discoveredAssets.some(a => a.type === 'tape')}
                <div class="space-y-4">
                    <SectionHeader title="Live hardware status" icon={Cpu} iconColor="text-blue-500" />

                    <div class="grid grid-cols-1 gap-6">
                        {#each discoveredAssets.filter(a => a.type === 'tape') as drive}
                            {@const info = drive.hardware_info}
                            <Card class="bg-bg-secondary border-blue-500/30 shadow-2xl relative overflow-hidden">
                                <div class="p-6 flex flex-col lg:flex-row gap-8">
                                    <!-- Drive Info -->
                                    <div class="flex-1 space-y-4">
                                        <div>
                                            <div class="text-[10px] font-medium text-text-secondary opacity-50 mb-2 flex items-center gap-2">
                                                <Cpu size={12} /> Physical tape drive
                                            </div>
                                            <div class="flex items-center gap-4">
                                                <div class="flex items-baseline gap-2">
                                                    <h3 class="text-2xl font-bold text-text-primary tracking-tight">{info?.drive?.vendor || 'Unknown'}</h3>
                                                    <span class="text-lg font-medium text-text-secondary opacity-40">{info?.drive?.model || 'Generic LTO'}</span>
                                                </div>
                                                {#if info?.tape}
                                                    <StatusBadge variant="blue">
                                                        <div class="w-1.5 h-1.5 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)] animate-pulse"></div>
                                                        Online
                                                    </StatusBadge>
                                                {:else}
                                                    <StatusBadge variant="neutral">No tape</StatusBadge>
                                                {/if}
                                            </div>
                                            <div class="mt-2 flex items-center gap-4 text-xs font-mono text-text-secondary/60">
                                                <span>FIRMWARE: <span class="text-text-primary">{info?.drive?.firmware || 'N/A'}</span></span>
                                                <span class="h-3 w-px bg-border-color"></span>
                                                <span>DEVICE: <span class="text-text-primary">{drive.device_path || '/dev/nst0'}</span></span>
                                            </div>
                                        </div>

                                        <!-- Live Performance / Health Dashboard -->
                                        {#if info?.tape}
                                            <div class="grid grid-cols-2 gap-4 pt-4 border-t border-border-color/30">
                                                <div class="bg-bg-primary/50 p-3 rounded-xl border border-border-color/50">
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-2">Session performance</span>
                                                    <div class="space-y-2">
                                                        <div class="flex justify-between items-center text-xs">
                                                            <span class="text-text-secondary flex items-center gap-1.5"><ArrowUp size={10} class="text-blue-400" /> Written</span>
                                                            <span class="text-text-primary font-medium mono">{(info.tape?.session_mib_written || 0).toLocaleString()} MiB</span>
                                                        </div>
                                                        <div class="flex justify-between items-center text-xs">
                                                            <span class="text-text-secondary flex items-center gap-1.5"><ArrowDown size={10} class="text-success-color" /> Read</span>
                                                            <span class="text-text-primary font-medium mono">{(info.tape?.session_mib_read || 0).toLocaleString()} MiB</span>
                                                        </div>
                                                    </div>
                                                </div>

                                                <div class="bg-bg-primary/50 p-3 rounded-xl border border-border-color/50">
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-2">Hardware health</span>
                                                    {#if info.tape?.alerts && info.tape.alerts.length > 0}
                                                        <div class="space-y-1">
                                                            {#each info.tape.alerts as alert}
                                                                <div class="flex items-center gap-2 text-[10px] font-semibold text-orange-400">
                                                                    <ShieldAlert size={10} /> {alert}
                                                                </div>
                                                            {/each}
                                                        </div>
                                                    {:else}
                                                        <div class="flex items-center gap-2 text-xs font-semibold text-success-color">
                                                            <ShieldCheck size={14} /> System healthy
                                                        </div>
                                                        <span class="text-[10px] text-text-secondary opacity-40 block mt-1">No active TapeAlerts</span>
                                                    {/if}
                                                </div>
                                            </div>

                                            <div class="grid grid-cols-3 gap-4 pt-2">
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Load count</span>
                                                    <span class="text-base font-bold text-text-primary mono flex items-center gap-2">
                                                        <RotateCw size={14} class="text-blue-500 opacity-50" />
                                                        {info.tape?.load_count || '0'}
                                                    </span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Current tape</span>
                                                    <span class="text-base font-bold text-text-primary mono">{drive.identifier || 'Unknown'}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">File number</span>
                                                    <span class="text-base font-bold text-text-primary mono">{info.file_number ?? 'N/A'}</span>
                                                </div>
                                            </div>

                                            <!-- Tape Operation Buttons -->
                                            <div class="pt-4 border-t border-border-color/30">
                                                <div class="flex gap-2">
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        class="h-8 text-xs flex-1 border-border-color/60 text-text-secondary hover:bg-white/5"
                                                        onclick={() => handleTapeRewind(drive.device_path)}
                                                        disabled={!!tapeOperationLoading}
                                                    >
                                                        {#if tapeOperationLoading === `rewind-${drive.device_path}`}
                                                            <RotateCw size={12} class="animate-spin mr-1.5" />
                                                            Rewinding...
                                                        {:else}
                                                            <SkipBack size={12} class="mr-1.5" />
                                                            Rewind
                                                        {/if}
                                                    </Button>
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        class="h-8 text-xs flex-1 border-border-color/60 text-text-secondary hover:bg-white/5"
                                                        onclick={() => handleTapeEject(drive.device_path)}
                                                        disabled={!!tapeOperationLoading}
                                                    >
                                                        {#if tapeOperationLoading === `eject-${drive.device_path}`}
                                                            <RotateCw size={12} class="animate-spin mr-1.5" />
                                                            Ejecting...
                                                        {:else}
                                                            <Upload size={12} class="mr-1.5" />
                                                            Eject
                                                        {/if}
                                                    </Button>
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        class="h-8 text-xs flex-1 border-red-500/30 text-red-400 hover:bg-red-500/10 hover:border-red-500/50"
                                                        onclick={() => openReinitConfirm(drive)}
                                                        disabled={!!tapeOperationLoading}
                                                    >
                                                        {#if tapeOperationLoading === `reinit-${drive.device_path}`}
                                                            <RotateCw size={12} class="animate-spin mr-1.5" />
                                                            Erasing...
                                                        {:else}
                                                            <AlertOctagon size={12} class="mr-1.5" />
                                                            Re-init
                                                        {/if}
                                                    </Button>
                                                </div>
                                            </div>
                                        {:else}
                                            <div class="pt-4 border-t border-border-color/30">
                                                <div class="flex items-center gap-2 text-xs text-text-secondary opacity-60">
                                                    <AlertTriangle size={14} />
                                                    No tape loaded in drive
                                                </div>
                                            </div>
                                        {/if}
                                    </div>

                                    <!-- Media/MAM Info (only if tape is loaded) -->
                                    {#if info?.tape}
                                        <div class="flex-1 bg-bg-primary/30 rounded-xl p-5 border border-border-color/50 relative">
                                            <div class="text-[10px] font-medium text-text-secondary opacity-50 mb-5 flex items-center justify-between">
                                                <div class="flex items-center gap-2"><Database size={12} /> Medium metadata (MAM)</div>
                                                <span class="text-blue-400 font-medium mono">{info.tape?.barcode || 'NO BARCODE'}</span>
                                            </div>

                                            <div class="grid grid-cols-2 gap-y-5 gap-x-8">
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Manufacturer</span>
                                                    <span class="text-xs font-semibold text-text-primary">{info.tape?.manufacturer || 'Unknown'}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Media serial</span>
                                                    <span class="text-xs font-semibold text-text-primary mono">{info.tape?.serial || 'N/A'}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">LTO generation</span>
                                                    <span class="inline-flex items-center px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[10px] font-semibold border border-blue-500/20">
                                                        {info.tape?.generation_label || info.tape?.generation || 'LTO'}
                                                    </span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Manufacture date</span>
                                                    <span class="text-xs font-semibold text-text-primary mono">{info.tape?.manufacture_date || 'N/A'}</span>
                                                </div>

                                                <div class="col-span-2 space-y-3 pt-1">
                                                    <!-- Capacity Utilization -->
                                                    {#if info.tape?.remaining_capacity_mib !== undefined && info.tape?.max_capacity_mib}
                                                        {@const used_mib = info.tape.max_capacity_mib - info.tape.remaining_capacity_mib}
                                                        {@const perc = Math.min(100, Math.round((used_mib / info.tape.max_capacity_mib) * 100))}
                                                        <div>
                                                            <div class="flex justify-between items-end mb-1.5">
                                                                <span class="text-[10px] font-medium text-text-secondary opacity-40">Physical capacity utilization</span>
                                                                <span class="text-xs font-bold text-blue-400 mono">{perc}%</span>
                                                            </div>
                                                            <ProgressBar value={perc} size="sm" />
                                                            <div class="flex justify-between mt-1 text-[9px] font-medium text-text-secondary/50 mono">
                                                                <span>Used: {(used_mib * 1.048576 / 1000).toFixed(1)} GB</span>
                                                                <span>Free: {(info.tape.remaining_capacity_mib * 1.048576 / 1000).toFixed(1)} GB</span>
                                                            </div>
                                                        </div>
                                                    {/if}

                                                    <div>
                                                        <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-1">Inserted tape identifier</span>
                                                        <div class="bg-bg-secondary p-2.5 rounded-lg border border-border-color font-mono text-xs text-text-primary italic shadow-inner">
                                                            "{info.tape?.barcode || 'NO BARCODE'}"
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    {/if}
                                </div>
                            </Card>
                        {/each}
                    </div>
                </div>
            {/if}

            <!-- Active Media -->
            <div class="space-y-4" data-testid="active-media-section">
                <SectionHeader title="Active archive media" icon={Database} iconColor="text-blue-500" />

                <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden flex flex-col">
                    <div class="px-6 py-2.5 bg-bg-tertiary/30 border-b border-border-color flex items-center justify-end gap-6">
                        <div class="flex items-center gap-2">
                            <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
                            <span class="text-[10px] font-medium text-text-secondary opacity-70">Identified & online</span>
                        </div>
                        <div class="h-3 w-px bg-border-color mx-2"></div>
                        <div class="flex items-center gap-2">
                            <Star size={10} class="text-yellow-500" fill="currentColor" />
                            <span class="text-[10px] font-medium text-text-secondary opacity-70">Next archival target</span>
                        </div>
                    </div>
                    <table class="w-full border-collapse">
                        <thead>
                            <tr class="bg-bg-tertiary/50 border-b border-border-color">
                                <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary">Drag</th>
                                <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary">#</th>
                                <th class="px-2 py-3 w-12 text-center text-xs font-semibold text-text-secondary">Stat</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary">Identity</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary">Type & tier</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary">Location</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary">Utilization</th>
                                <th class="px-6 py-3 text-right text-xs font-semibold text-text-secondary">Actions</th>
                            </tr>
                        </thead>
                        {#if activeMedia.length > 0}
                            <tbody
                                use:dndzone={{items: activeMedia, flipDurationMs: 200}}
                                onconsider={handleDndConsider}
                                onfinalize={handleDndFinalize}
                                class="divide-y divide-border-color/30"
                            >
                                {#each activeMedia as media (media.id)}
                                    <tr class="hover:bg-bg-primary/30 transition-colors group">
                                        <td class="px-6 py-4 text-center">
                                            <div class="cursor-grab active:cursor-grabbing text-text-secondary opacity-20 group-hover:opacity-100 transition-opacity">
                                                <GripVertical size={16} />
                                            </div>
                                        </td>
                                        {@render mediaRow(media)}
                                    </tr>
                                {/each}
                            </tbody>
                        {:else}
                            <tbody class="divide-y divide-border-color/30">
                                <tr><td colspan="8" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-medium">No active archive media</p></td></tr>
                            </tbody>
                        {/if}
                    </table>
                </Card>
            </div>

            <!-- Fully Utilized Media -->
            {#if fullMedia.length > 0}
                <div class="space-y-4" data-testid="full-media-section">
                    <SectionHeader title="Fully utilized media" icon={ShieldCheck} iconColor="text-success-color" />

                    <Card class="bg-bg-secondary/80 border border-border-color/80 rounded-xl overflow-hidden shadow-xl">
                        <table class="w-full border-collapse">
                            <thead>
                                <tr class="bg-bg-tertiary/30 border-b border-border-color/50">
                                    <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-60">Sort</th>
                                    <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-60">#</th>
                                    <th class="px-2 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-60">Stat</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-60">Identity</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-60">Type & tier</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-60">Location</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-60">Utilization</th>
                                    <th class="px-6 py-3 text-right text-xs font-semibold text-text-secondary opacity-60">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-border-color/30">
                                {#each fullMedia as media (media.id)}
                                    <tr class="hover:bg-bg-primary/20 transition-colors">
                                        <td class="px-6 py-4 text-center opacity-30">
                                            <Minus size={16} />
                                        </td>
                                        {@render mediaRow(media)}
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </Card>
                </div>
            {/if}

            <!-- Retired & Failed Media -->
            {#if unavailableMedia.length > 0}
                <div class="space-y-4" data-testid="unavailable-media-section">
                    <SectionHeader title="Retired & failed media" icon={ShieldAlert} iconColor="text-error-color" />

                    <Card class="bg-bg-secondary/60 border border-border-color/60 rounded-xl overflow-hidden shadow-xl grayscale-[0.5] opacity-80">
                        <table class="w-full border-collapse">
                            <thead>
                                <tr class="bg-bg-tertiary/20 border-b border-border-color/40">
                                    <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-40">Sort</th>
                                    <th class="px-6 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-40">#</th>
                                    <th class="px-2 py-3 w-12 text-center text-xs font-semibold text-text-secondary opacity-40">Stat</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-40">Identity</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-40">Type & tier</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-40">Location</th>
                                    <th class="px-6 py-3 text-left text-xs font-semibold text-text-secondary opacity-40">Utilization</th>
                                    <th class="px-6 py-3 text-right text-xs font-semibold text-text-secondary opacity-40">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-border-color/20">
                                {#each unavailableMedia as media (media.id)}
                                    <tr class="hover:bg-bg-primary/20 transition-colors">
                                        <td class="px-6 py-4 text-center opacity-20">
                                            <Minus size={16} />
                                        </td>
                                        {@render mediaRow(media)}
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </Card>
                </div>
            {/if}
        </section>
    </div>

    <!-- Registration Dialog -->
    <Dialog show={showRegisterDialog} onClose={() => showRegisterDialog = false} ariaLabelledBy="register-title">
        <Card class="w-[700px] max-h-[90vh] overflow-y-auto p-8 flex flex-col gap-6 shadow-2xl">
            <header class="flex justify-between items-start">
                <div>
                    <h2 id="register-title" class="text-xl font-bold text-text-primary">Add new media</h2>
                    <p class="text-sm text-text-secondary mt-1 opacity-60">Add physical storage locations for your backups.</p>
                </div>
                <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => showRegisterDialog = false}><X size={20} /></Button>
            </header>

    <div class="flex gap-3 overflow-x-auto shrink-0 pb-3">
        {#each providersList.filter(p => !['mock_lto'].includes(p.provider_id)) as provider}
            <button class={cn("flex-none w-32 flex flex-col items-center gap-3 p-4 rounded-xl border-2 transition-all", newMedia.media_type === provider.provider_id ? "bg-blue-500/10 border-blue-500 text-blue-400 shadow-lg shadow-blue-500/10" : "bg-bg-primary/50 border-border-color text-text-secondary hover:border-text-secondary/30")}
                onclick={() => {
                    newMedia.media_type = provider.provider_id;
                    newMedia.credential_key = '';
                    newMedia.oauth_email = '';
                    if (provider.provider_id === 'lto_tape') {
                        newMedia.location = 'Storage Shelf';
                        newMedia.generation = 'LTO-6';
                        newMedia.capacity = LTO_CAPACITY['LTO-6'];
                    } else if (provider.provider_id === 'local_hdd') {
                        newMedia.location = 'Offsite Safe';
                    } else if (provider.provider_id === 'google_drive' || provider.provider_id === 'dropbox') {
                        newMedia.location = 'Cloud';
                        newMedia.capacity = 0;
                    } else {
                        newMedia.location = 'Cloud';
                        handleProviderTemplateChange('aws');
                    }
                }}
            >
                {@render ConfigIcon(provider.provider_id)}
                <span class="text-xs font-semibold">{provider.name}</span>
            </button>
        {/each}
    </div>

            <div class="space-y-6">
                <!-- Identity Section -->
                <div class="space-y-4">
                    <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">Identity</h3>
                    <div class="grid grid-cols-2 gap-6">
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="identifier">
                                {newMedia.media_type === 'lto_tape' ? 'Barcode' : newMedia.media_type === 'local_hdd' ? 'Identifier / Serial' : 'Friendly Name'}
                            </label>
                            <Input id="identifier" bind:value={newMedia.identifier} placeholder={newMedia.media_type === 'lto_tape' ? 'TAPE01' : newMedia.media_type === 'local_hdd' ? 'Samsung-T7-001' : newMedia.media_type === 'google_drive' ? 'GDrive-Backup-01' : newMedia.media_type === 'dropbox' ? 'Dropbox-Backup-01' : 'AWS-Production'} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                        </div>

                        {#if newMedia.media_type === 'lto_tape'}
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="generation">LTO Generation</label>
                                <div class="relative">
                                    <select id="generation" bind:value={newMedia.generation} onchange={() => handleGenerationChange(newMedia.generation)} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                        <option value="LTO-5">LTO-5 (1.5 TB)</option>
                                        <option value="LTO-6">LTO-6 (2.5 TB)</option>
                                        <option value="LTO-7">LTO-7 (6.0 TB)</option>
                                        <option value="LTO-8">LTO-8 (12.0 TB)</option>
                                        <option value="LTO-9">LTO-9 (18.0 TB)</option>
                                    </select>
                                    <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                </div>
                            </div>
                        {:else if newMedia.media_type === 'local_hdd'}
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="drive_model">Drive Model</label>
                                <Input id="drive_model" bind:value={newMedia.drive_model} placeholder="Samsung T7 Shield" class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                        {:else if newMedia.media_type === 's3_compat'}
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="bucket_name">Bucket Name</label>
                                <Input id="bucket_name" bind:value={newMedia.bucket_name} placeholder="my-backup-bucket" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                        {/if}
                    </div>

                    {#if newMedia.media_type === 'local_hdd'}
                        <div class="grid grid-cols-2 gap-6">
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="device_uuid">Device UUID</label>
                                <Input id="device_uuid" bind:value={newMedia.device_uuid} placeholder="12345678-ABCD" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="mount_path">Expected Mount Path</label>
                                <Input id="mount_path" bind:value={newMedia.mount_path} placeholder="/Volumes/Backup-01" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                        </div>
                    {/if}

                    {#if newMedia.media_type === 's3_compat'}
                        <div class="grid grid-cols-2 gap-6">
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="provider_template">Provider Template</label>
                                <div class="relative">
                                    <select id="provider_template" bind:value={newMedia.provider_template} onchange={() => handleProviderTemplateChange(newMedia.provider_template)} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                        <option value="aws">AWS S3</option>
                                        <option value="minio">MinIO</option>
                                        <option value="wasabi">Wasabi</option>
                                        <option value="backblaze">Backblaze B2</option>
                                        <option value="digitalocean">DigitalOcean Spaces</option>
                                        <option value="custom">Custom</option>
                                    </select>
                                    <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                </div>
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="region">Region</label>
                                <Input id="region" bind:value={newMedia.region} placeholder="us-east-1" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-6">
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="endpoint_url">Endpoint URL</label>
                                <Input id="endpoint_url" bind:value={newMedia.endpoint_url} placeholder="https://s3.amazonaws.com" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="access_key_id">Access Key ID</label>
                                <Input id="access_key_id" bind:value={newMedia.access_key_id} placeholder="AKIA..." class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" type="password" />
                            </div>
                        </div>
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="secret_access_key_name">Secret Access Key</label>
                            <div class="relative">
                                <select id="secret_access_key_name" bind:value={newMedia.secret_access_key_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                    <option value="">None (unauthenticated)</option>
                                    {#each secretsList as secret}
                                        <option value={secret}>{secret}</option>
                                    {/each}
                                </select>
                                <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                            </div>
                            <p class="text-[10px] text-text-secondary leading-tight opacity-60">Manage secrets in <a href="/settings" class="text-blue-500 hover:underline">Settings</a>.</p>
                        </div>
                    {/if}
                </div>

                <!-- Capacity -->
                <div class="space-y-2">
                    <label class="text-xs font-medium text-text-secondary ml-1" for="capacity">Capacity (GB)</label>
                    <Input id="capacity" type="number" bind:value={newMedia.capacity} class="h-10 bg-bg-primary/50 border-border-color font-mono" />
                    {#if newMedia.media_type === 'lto_tape'}
                        <p class="text-[10px] text-text-secondary leading-tight opacity-60">Auto-populated from LTO generation. You can manually adjust.</p>
                    {/if}
                </div>

                <!-- Location Section -->
                <div class="space-y-4">
                    <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">Location</h3>
                    {#if newMedia.media_type !== 's3_compat' && newMedia.media_type !== 'google_drive' && newMedia.media_type !== 'dropbox'}
                        <div class="grid grid-cols-4 gap-4">
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="location_building">Building</label>
                                <Input id="location_building" bind:value={newMedia.location_building} placeholder="Office" class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="location_room">Room/Vault</label>
                                <Input id="location_room" bind:value={newMedia.location_room} placeholder="Tape Vault A" class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="location_rack">Rack/Shelf</label>
                                <Input id="location_rack" bind:value={newMedia.location_rack} placeholder="Rack-12" class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="location_slot">Slot/Position</label>
                                <Input id="location_slot" bind:value={newMedia.location_slot} placeholder="Slot-45" class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                        </div>
                    {:else}
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="location">Friendly Location Label</label>
                            <div class="relative">
                                <MapPin size={16} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                                <Input id="location" bind:value={newMedia.location} placeholder="US-East Data Center" class="h-10 bg-bg-primary/50 pl-12 border-border-color text-sm" />
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Configuration Section -->
                <div class="space-y-4">
                    <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">Configuration</h3>

                    {#if newMedia.media_type === 'lto_tape'}
                        <div class="flex items-center gap-3 h-10 px-1">
                            <input id="compression" type="checkbox" bind:checked={newMedia.compression} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                            <label class="text-xs font-medium text-text-secondary cursor-pointer" for="compression">Hardware Compression</label>
                        </div>
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="lto-encryption_secret_name">Encryption Secret</label>
                            <div class="relative">
                                <select id="lto-encryption_secret_name" bind:value={newMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                    <option value="">None (no encryption)</option>
                                    {#each secretsList as secret}
                                        <option value={secret}>{secret}</option>
                                    {/each}
                                </select>
                                <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                            </div>
                            <p class="text-[10px] text-text-secondary leading-tight opacity-60">Manage secrets in <a href="/settings" class="text-blue-500 hover:underline">Settings</a>.</p>
                        </div>
                    {:else if newMedia.media_type === 'local_hdd'}
                        <div class="flex items-center gap-3 h-10 px-1">
                            <input id="is_ssd" type="checkbox" bind:checked={newMedia.is_ssd} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                            <label class="text-xs font-medium text-text-secondary cursor-pointer" for="is_ssd">SSD (Solid State Drive)</label>
                        </div>
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="hdd-encryption_secret_name">Encryption Secret</label>
                            <div class="relative">
                                <select id="hdd-encryption_secret_name" bind:value={newMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                    <option value="">None (no encryption)</option>
                                    {#each secretsList as secret}
                                        <option value={secret}>{secret}</option>
                                    {/each}
                                </select>
                                <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                            </div>
                            <p class="text-[10px] text-text-secondary leading-tight opacity-60">Manage secrets in <a href="/settings" class="text-blue-500 hover:underline">Settings</a>.</p>
                        </div>
                    {:else if newMedia.media_type === 's3_compat'}
                        <div class="grid grid-cols-2 gap-4">
                            <div class="flex items-center gap-3 h-10 px-1">
                                <input id="path_style_access" type="checkbox" bind:checked={newMedia.path_style_access} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                <label class="text-xs font-medium text-text-secondary cursor-pointer" for="path_style_access">Path-Style Access (MinIO/Self-hosted)</label>
                            </div>
                            <div class="flex items-center gap-3 h-10 px-1">
                                <input id="obfuscate_filenames" type="checkbox" bind:checked={newMedia.obfuscate_filenames} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                <label class="text-xs font-medium text-text-secondary cursor-pointer" for="obfuscate_filenames">Obfuscate Filenames</label>
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-6">
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="storage_class">Storage Class</label>
                                <Input id="storage_class" bind:value={newMedia.storage_class} placeholder="Standard, Glacier, etc." class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="max_part_size_mb">Max Part Size (MB)</label>
                                <Input id="max_part_size_mb" type="number" bind:value={newMedia.max_part_size_mb} class="h-10 bg-bg-primary/50 border-border-color font-mono" />
                            </div>
                        </div>
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="encryption_secret_name">Encryption Secret</label>
                            <div class="relative">
                                <select id="encryption_secret_name" bind:value={newMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                    <option value="">None (no encryption)</option>
                                    {#each secretsList as secret}
                                        <option value={secret}>{secret}</option>
                                    {/each}
                                </select>
                                <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                            </div>
                            <p class="text-[10px] text-text-secondary leading-tight opacity-60">Manage secrets in <a href="/settings" class="text-blue-500 hover:underline">Settings</a>.</p>
                        </div>
                    {:else if newMedia.media_type === 'google_drive' || newMedia.media_type === 'dropbox'}
                        <!-- OAuth connect section -->
                        <div class="space-y-3">
                            <p class="text-[10px] text-text-secondary leading-relaxed opacity-70">
                                {newMedia.media_type === 'google_drive'
                                    ? 'Store archives in a Google Drive folder. Requires OAuth2 authorization. Set google_drive_client_id and google_drive_client_secret in the Secrets keystore first.'
                                    : 'Store archives in a Dropbox folder. Requires OAuth2 authorization. Set dropbox_app_key and dropbox_app_secret in the Secrets keystore first.'}
                            </p>
                            {#if newMedia.oauth_email}
                                <div class="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-xl">
                                    <div class="w-2 h-2 rounded-full bg-green-400 shrink-0"></div>
                                    <span class="text-xs text-green-400 font-medium">Connected as {newMedia.oauth_email}</span>
                                </div>
                            {:else}
                                <Button
                                    variant="outline"
                                    class="w-full h-10 gap-2"
                                    onclick={() => startOAuth(newMedia.media_type as 'google_drive' | 'dropbox')}
                                    disabled={newMedia.oauth_polling}
                                >
                                    {#if newMedia.oauth_polling}
                                        <RotateCw size={14} class="animate-spin" />
                                        Waiting for authorization…
                                    {:else}
                                        <Cloud size={14} />
                                        {newMedia.media_type === 'google_drive' ? 'Connect with Google' : 'Connect with Dropbox'}
                                    {/if}
                                </Button>
                            {/if}
                        </div>
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-text-secondary ml-1" for="oauth-encryption_secret_name">Encryption Secret</label>
                            <div class="relative">
                                <select id="oauth-encryption_secret_name" bind:value={newMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                    <option value="">None (no encryption)</option>
                                    {#each secretsList as secret}
                                        <option value={secret}>{secret}</option>
                                    {/each}
                                </select>
                                <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                            </div>
                            <p class="text-[10px] text-text-secondary leading-tight opacity-60">Manage secrets in <a href="/settings" class="text-blue-500 hover:underline">Settings</a>.</p>
                        </div>
                        <div class="flex items-center gap-3 p-3 rounded-xl border border-border-color bg-bg-primary/30">
                            <input id="oauth-obfuscate_filenames" type="checkbox" bind:checked={newMedia.obfuscate_filenames} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                            <label class="text-xs font-medium text-text-secondary cursor-pointer" for="oauth-obfuscate_filenames">Obfuscate Filenames</label>
                        </div>
                    {/if}
                </div>
            </div>

            <footer class="flex gap-3 pt-4 border-t border-border-color">
                <Button variant="outline" class="flex-1 h-10" onclick={() => showRegisterDialog = false}>Cancel</Button>
                <Button variant="default" class="flex-[2] h-10" onclick={handleRegister}>Register media</Button>
            </footer>
        </Card>
    </Dialog>

    <!-- Edit Dialog -->
    <Dialog show={!!editingMedia} onClose={() => editingMedia = null} ariaLabelledBy="edit-title">
        {#if editingMedia}
            <Card class="w-[600px] max-h-[90vh] overflow-y-auto p-8 flex flex-col gap-6 shadow-2xl">
                <header class="flex justify-between items-start">
                    <div>
                        <h2 id="edit-title" class="text-xl font-bold text-text-primary flex items-center gap-3">
                            <Edit3 size={20} class="text-blue-500" />
                            Edit media config
                        </h2>
                        <p class="text-sm text-text-secondary mt-1 opacity-60">Update hardware paths and physical location.</p>
                    </div>
                    <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => editingMedia = null}><X size={20} /></Button>
                </header>

                <div class="space-y-6">
                    <div class="p-4 bg-bg-primary/50 border border-border-color rounded-xl flex items-center gap-4">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 shrink-0">
                            {@render ConfigIcon(editingMedia.media_type)}
                        </div>
                        <div>
                            <span class="text-sm font-semibold text-text-primary">{editingMedia.identifier}</span>
                            <span class="text-xs text-text-secondary block opacity-60">{editingMedia.media_type} &bull; {editingMedia.generation || editingMedia.generation_tier || 'Generic'}</span>
                        </div>
                    </div>

                    <!-- Location Fields -->
                    <div class="space-y-4">
                        <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">Location</h3>
                        {#if editingMedia.media_type !== 's3_compat'}
                            <div class="grid grid-cols-4 gap-4">
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location_building">Building</label>
                                    <Input id="edit-location_building" bind:value={editingMedia.location_building} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location_room">Room/Vault</label>
                                    <Input id="edit-location_room" bind:value={editingMedia.location_room} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location_rack">Rack/Shelf</label>
                                    <Input id="edit-location_rack" bind:value={editingMedia.location_rack} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location_slot">Slot/Position</label>
                                    <Input id="edit-location_slot" bind:value={editingMedia.location_slot} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                                </div>
                            </div>
                        {:else}
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location">Location Label</label>
                                <Input id="edit-location" bind:value={editingMedia.location} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                            </div>
                        {/if}
                    </div>

                    <!-- Capacity -->
                    <div class="space-y-2">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="edit-capacity">Capacity (GB)</label>
                        <Input id="edit-capacity" type="number" bind:value={editingMedia.capacity} class="h-10 bg-bg-primary/50 border-border-color font-mono" />
                    </div>

                    <!-- Type-Specific Edit Fields -->
                    {#if editingMedia.media_type === 'lto_tape'}
                        <div class="space-y-4">
                            <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">LTO Configuration</h3>
                            <div class="flex items-center gap-3 h-10 px-1">
                                <input id="edit-compression" type="checkbox" bind:checked={editingMedia.compression} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                <label class="text-xs font-medium text-text-secondary cursor-pointer" for="edit-compression">Hardware Compression</label>
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="edit-lto-encryption_secret_name">Encryption Secret</label>
                                <div class="relative">
                                    <select id="edit-lto-encryption_secret_name" bind:value={editingMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                        <option value="">None (no encryption)</option>
                                        {#each secretsList as secret}
                                            <option value={secret}>{secret}</option>
                                        {/each}
                                    </select>
                                    <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                </div>
                            </div>
                        </div>
                    {:else if editingMedia.media_type === 'local_hdd'}
                        <div class="space-y-4">
                            <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">HDD Configuration</h3>
                            <div class="grid grid-cols-2 gap-4">
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-drive_model">Drive Model</label>
                                    <Input id="edit-drive_model" bind:value={editingMedia.drive_model} class="h-10 bg-bg-primary/50 border-border-color text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-device_uuid">Device UUID</label>
                                    <Input id="edit-device_uuid" bind:value={editingMedia.device_uuid} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="flex items-center gap-3 h-10 px-1">
                                    <input id="edit-is_ssd" type="checkbox" bind:checked={editingMedia.is_ssd} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                    <label class="text-xs font-medium text-text-secondary cursor-pointer" for="edit-is_ssd">SSD</label>
                                </div>
                            </div>
                            <div class="space-y-2">
                                <label class="text-xs font-medium text-text-secondary ml-1" for="edit-hdd-encryption_secret_name">Encryption Secret</label>
                                <div class="relative">
                                    <select id="edit-hdd-encryption_secret_name" bind:value={editingMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                        <option value="">None (no encryption)</option>
                                        {#each secretsList as secret}
                                            <option value={secret}>{secret}</option>
                                        {/each}
                                    </select>
                                    <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                </div>
                            </div>
                        </div>
                    {:else if editingMedia.media_type === 's3_compat'}
                        <div class="space-y-4">
                            <h3 class="text-xs font-semibold text-text-secondary uppercase tracking-wider">Cloud Configuration</h3>
                            <div class="grid grid-cols-2 gap-4">
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-endpoint_url">Endpoint URL</label>
                                    <Input id="edit-endpoint_url" bind:value={editingMedia.endpoint_url} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-region">Region</label>
                                    <Input id="edit-region" bind:value={editingMedia.region} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-bucket_name">Bucket Name</label>
                                    <Input id="edit-bucket_name" bind:value={editingMedia.bucket_name} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-storage_class">Storage Class</label>
                                    <Input id="edit-storage_class" bind:value={editingMedia.storage_class} placeholder="STANDARD, GLACIER, etc." class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-access_key_id">Access Key ID</label>
                                    <Input id="edit-access_key_id" bind:value={editingMedia.access_key_id} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-secret_access_key_name">Secret Access Key</label>
                                    <div class="relative">
                                        <select id="edit-secret_access_key_name" bind:value={editingMedia.secret_access_key_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                            <option value="">None (unauthenticated)</option>
                                            {#each secretsList as secret}
                                                <option value={secret}>{secret}</option>
                                            {/each}
                                        </select>
                                        <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                    </div>
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="edit-encryption_secret_name">Encryption Secret</label>
                                    <div class="relative">
                                        <select id="edit-encryption_secret_name" bind:value={editingMedia.encryption_secret_name} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                            <option value="">None (no encryption)</option>
                                            {#each secretsList as secret}
                                                <option value={secret}>{secret}</option>
                                            {/each}
                                        </select>
                                        <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                    </div>
                                </div>
                                <div class="flex items-center gap-3 h-10 px-1">
                                    <input id="edit-path_style_access" type="checkbox" bind:checked={editingMedia.path_style_access} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                    <label class="text-xs font-medium text-text-secondary cursor-pointer" for="edit-path_style_access">Path-Style Access</label>
                                </div>
                                <div class="flex items-center gap-3 h-10 px-1">
                                    <input id="edit-obfuscate_filenames" type="checkbox" bind:checked={editingMedia.obfuscate_filenames} class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20" />
                                    <label class="text-xs font-medium text-text-secondary cursor-pointer" for="edit-obfuscate_filenames">Obfuscate Filenames</label>
                                </div>
                            </div>
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="edit-status">Status</label>
                        <div class="relative">
                            <select
                                id="edit-status"
                                bind:value={editingMedia.status}
                                class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer"
                            >
                                <option value="active">Active</option>
                                <option value="full">Fully Utilized</option>
                                <option value="retired">Retired</option>
                                <option value="failed">Hardware Failure</option>
                            </select>
                            <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                        </div>
                    </div>
                </div>

                <footer class="flex gap-3 pt-4 border-t border-border-color">
                    <Button variant="outline" class="flex-1 h-10" onclick={() => editingMedia = null}>Cancel</Button>
                    <Button variant="default" class="flex-[2] h-10" onclick={handleUpdate}>
                        <Save size={16} class="mr-2" /> Save changes
                    </Button>
                </footer>
            </Card>
        {/if}
    </Dialog>

    <!-- Re-initialize Confirmation Dialog -->
    <Dialog show={showReinitConfirmDialog} onClose={() => showReinitConfirmDialog = false} ariaLabelledBy="reinit-title">
        <Card class="w-[500px] p-8 flex flex-col gap-6 shadow-2xl">
            <header class="flex justify-between items-start">
                <div>
                    <h2 id="reinit-title" class="text-xl font-bold text-text-primary flex items-center gap-3 text-red-400">
                        <AlertOctagon size={24} />
                        Re-initialize Tape?
                    </h2>
                </div>
                <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => showReinitConfirmDialog = false}>
                    <X size={20} />
                </Button>
            </header>

            <div class="space-y-4">
                <div class="p-4 bg-red-500/10 border border-red-500/30 rounded-xl">
                    <p class="text-sm text-text-primary font-medium mb-2">This will clear the tape and remove all archive records from the database:</p>
                    <ul class="text-sm text-text-secondary space-y-1 list-disc list-inside">
                        <li>All archive records for this tape will be removed from the database</li>
                        <li>The tape is rewound and an end-of-file marker is written at the start — fast operation</li>
                        <li>You will need to use 'Initialize Media' to write a new label</li>
                    </ul>
                </div>

                <div class="p-4 bg-bg-primary/50 border border-border-color rounded-xl">
                    <p class="text-[10px] font-medium text-text-secondary opacity-50 mb-1">Target device</p>
                    <p class="text-sm font-mono text-text-primary">{reinitTargetDrive?.device_path || 'Unknown'}</p>
                    <p class="text-xs text-text-secondary mt-1">Tape: {reinitTargetDrive?.identifier || 'Unknown'}</p>
                </div>
            </div>

            <footer class="flex flex-col gap-3 pt-4 border-t border-border-color">
                <div class="flex gap-3">
                    <Button variant="outline" class="flex-1 h-10" onclick={() => showReinitConfirmDialog = false}>Cancel</Button>
                    <Button variant="default" class="flex-[2] h-10 bg-red-500 hover:bg-red-600 text-white" onclick={() => handleTapeReinitialize(false)}>
                        <AlertOctagon size={16} class="mr-2" />
                        Clear & Re-initialize
                    </Button>
                </div>
                <button
                    class="text-xs text-text-secondary/40 hover:text-red-400 transition-colors text-center underline underline-offset-2"
                    onclick={() => handleTapeReinitialize(true)}
                >
                    Secure erase (full SCSI erase — takes hours)
                </button>
            </footer>
        </Card>
    </Dialog>
</div>
