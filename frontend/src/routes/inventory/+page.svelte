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
        EyeOff
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
    import Dialog from '$lib/components/ui/Dialog.svelte';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import { cn } from '$lib/utils';
    import {
        listStorageFleetInventoryMediaGet,
        registerNewMediaInventoryMediaPost,
        deleteMediaAssetInventoryMediaMediaIdDelete,
        triggerBackupJobBackupsTriggerMediaIdPost,
        triggerAutoBackupBackupsTriggerAutoPost,
        initializeStorageHardwareInventoryMediaMediaIdInitializePost,
        reorderArchivalPriorityInventoryMediaReorderPost,
        updateMediaAssetInventoryMediaMediaIdPatch,
        discoverHardwareNodesSystemHardwareDiscoverGet,
        ignoreHardwareNodeSystemHardwareIgnorePost,
        listStorageProvidersInventoryProvidersGet,
        type MediaSchema,
        type StorageProviderSchema
    } from '$lib/api';
    import { dndzone } from 'svelte-dnd-action';
    import { toast } from 'svelte-sonner';
    import { beforeNavigate } from '$app/navigation';

    let mediaList = $state<MediaSchema[]>([]);
    let providersList = $state<StorageProviderSchema[]>([]);
    let discoveredAssets = $state<any[]>([]);
    let loading = $state(true);
    let showRegisterDialog = $state(false);
    let editingMedia = $state<MediaSchema | null>(null);

    // New Media Form State
    let newMedia = $state({
        media_type: 'lto_tape',
        identifier: '',
        generation_tier: 'LTO-6',
        capacity_gb: 2500,
        location: 'Storage Shelf'
    });

    let dynamicConfig = $state<Record<string, any>>({});

    const activeProvider = $derived(
        providersList.find(p => p.provider_id === newMedia.media_type)
    );

    // Initialize dynamicConfig when media_type changes
    $effect(() => {
        // Track provider identity changes
        const _id = activeProvider?.provider_id;

        if (activeProvider) {
            untrack(() => {
                const newConfig: Record<string, any> = {};
                Object.keys(activeProvider.config_schema).forEach(key => {
                    // Preserve existing value if key is the same, otherwise default empty
                    newConfig[key] = dynamicConfig[key] || '';
                });
                dynamicConfig = newConfig;
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
                .filter(m => m.is_online && m.config?.device_path)
                .map(m => m.config.device_path)
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
                listStorageFleetInventoryMediaGet({ query: { refresh } }),
                discoverHardwareNodesSystemHardwareDiscoverGet()
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
                         if (Object.keys(newAsset.hardware_info.tape || {}).length === 0 && Object.keys(oldAsset.hardware_info.tape || {}).length > 0) {
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

    let prevOnlineCount = $state(0);

    $effect(() => {
        const currentOnlineCount = mediaList.filter(m => m.is_online).length;
        if (currentOnlineCount > prevOnlineCount) {
            // New hardware detected online, trigger a forced refresh to identify it immediately
            loadMedia(true, true);
        }
        prevOnlineCount = currentOnlineCount;
    });

    onMount(async () => {
        // Initial load (non-silent and forced refresh to show live hardware status immediately)
        loadMedia(false, true);

        try {
            const res = await listStorageProvidersInventoryProvidersGet();
            if (res.data) providersList = res.data;
        } catch (error) {
            console.error("Failed to load storage providers:", error);
        }

        pollInterval = setInterval(() => loadMedia(true), 3000);
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
            await reorderArchivalPriorityInventoryMediaReorderPost({
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
            await initializeStorageHardwareInventoryMediaMediaIdInitializePost({
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
            await triggerBackupJobBackupsTriggerMediaIdPost({
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
            await triggerAutoBackupBackupsTriggerAutoPost({
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

        try {
            await registerNewMediaInventoryMediaPost({
                body: {
                    media_type: newMedia.media_type,
                    identifier: newMedia.identifier,
                    generation_tier: newMedia.generation_tier,
                    capacity: newMedia.capacity_gb * 1024 * 1024 * 1024,
                    location: newMedia.location,
                    config: dynamicConfig
                },
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
        editingMedia = JSON.parse(JSON.stringify(media));
    }

    async function handleUpdate() {
        if (!editingMedia) return;
        try {
            await updateMediaAssetInventoryMediaMediaIdPatch({
                path: { media_id: editingMedia.id },
                body: {
                    location: editingMedia.location,
                    status: editingMedia.status,
                    config: editingMedia.config
                },
                throwOnError: true
            });
            toast.success("Media configuration updated");
            editingMedia = null;
            loadMedia();
        } catch (error) {
            toast.error("Failed to update media");
        }
    }

    async function handleIgnoreAsset(identifier: string) {
        try {
            await ignoreHardwareNodeSystemHardwareIgnorePost({
                body: { identifier }
            });
            loadMedia();
        } catch (error) {
            toast.error("Failed to ignore asset");
        }
    }

    async function handleDelete(mediaId: number) {
        if (!confirm("Remove this media from inventory? Data on the physical media will remain, but TapeHoard will lose its index association.")) return;
        try {
            await deleteMediaAssetInventoryMediaMediaIdDelete({
                path: { media_id: mediaId }
            });
            toast.success("Media removed from inventory");
            loadMedia();
        } catch (error) {
            toast.error("Failed to delete media");
        }
    }

    function formatSize(bytes: number) {
        const gb = bytes / (1024 * 1024 * 1024);
        if (gb >= 1000) return `${(gb / 1024).toFixed(2)} TB`;
        return `${gb.toFixed(0)} GB`;
    }
</script>

{#snippet ConfigIcon(type: string)}
    {#if type === 'lto_tape' || type === 'tape'}<CassetteTape size={24} />
    {:else if type === 'local_hdd' || type === 'hdd'}<HardDrive size={24} />
    {:else}<Cloud size={24} />{/if}
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
        <div class="flex flex-col min-w-0">
            <span class="text-sm font-semibold text-text-primary truncate">{media.identifier}</span>
            <div class="mt-0.5 flex flex-col gap-0.5">
                {#if (media.media_type === 'local_hdd' || media.media_type === 'hdd') && media.config?.mount_path}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[10px] mono truncate">
                        <Monitor size={10} /> {media.config.mount_path}
                    </div>
                {:else if media.media_type === 's3_compat' && media.config?.bucket_name}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[10px] mono truncate">
                        <Globe size={10} /> {media.config.bucket_name}
                    </div>
                {/if}
                <div class="flex gap-2 mt-0.5">
                    {#if media.status === 'failed'}
                        <StatusBadge variant="error">Hardware failure</StatusBadge>
                    {:else if media.status === 'retired'}
                        <StatusBadge variant="neutral">Retired</StatusBadge>
                    {/if}

                    {#if media.config?.encryption_key || media.config?.encryption_passphrase}
                        <StatusBadge variant="info">
                            <ShieldCheck size={8} /> Encrypted
                        </StatusBadge>
                    {/if}
                </div>
            </div>
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex flex-col">
            <span class="text-xs font-medium text-text-secondary">{media.media_type}</span>
            <div class="flex items-center gap-2 mt-0.5">
                <span class="text-[10px] font-medium text-text-secondary/40">{media.generation_tier || 'Generic'}</span>
                {#if (media.media_type === 'local_hdd' || media.media_type === 'hdd') && media.config?.device_uuid}
                    <span class="text-[10px] mono text-text-secondary/30 truncate max-w-[80px]">{media.config.device_uuid}</span>
                {/if}
            </div>
        </div>
    </td>
    <td class="px-6 py-3">
        <div class="flex items-center gap-1.5 text-text-secondary">
            <MapPin size={12} class="opacity-40" />
            <span class="text-xs font-medium">{media.location || 'Unknown'}</span>
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
                                                    <span class="text-[9px] font-medium bg-white/5 px-1.5 py-0.5 rounded border border-white/10 text-text-secondary">MFR: {asset.hardware_info.tape.manufacturer}</span>
                                                    <span class="text-[9px] font-medium bg-blue-500/10 px-1 rounded border border-blue-500/20 text-blue-400">{asset.hardware_info.tape.generation_label || asset.hardware_info.tape.generation}</span>
                                                </div>
                                            {/if}
                                        </div>
                                    {/if}

                                    <div class="mt-4 flex gap-2">
                                        <Button variant="default" size="sm" class="h-8 text-xs flex-1" onclick={() => {
                                            newMedia.media_type = asset.type === 'tape' ? 'lto_tape' : 'local_hdd';
                                            newMedia.identifier = asset.identifier === 'Unrecognized Disk' ? '' : asset.identifier;

                                            // Pre-fill dynamic config
                                            if (asset.type === 'hdd') {
                                                dynamicConfig.mount_path = asset.mount_path;
                                                dynamicConfig.device_uuid = asset.device_uuid || '';
                                                if (asset.capacity_bytes) {
                                                    newMedia.capacity_gb = Math.floor(asset.capacity_bytes / (1024 * 1024 * 1024));
                                                }
                                            } else if (asset.type === 'tape') {
                                                dynamicConfig.device_path = asset.device_path;
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
            <!-- Hardware Status -->
            {#if mediaList.some(m => m.is_online && (m.media_type === 'lto_tape' || m.media_type === 'tape'))}
                <div class="space-y-4">
                    <SectionHeader title="Live hardware status" icon={Cpu} iconColor="text-blue-500" />

                    <div class="grid grid-cols-1 gap-6">
                        {#each mediaList.filter(m => m.is_online && (m.media_type === 'lto_tape' || m.media_type === 'tape')) as media}
                            {#if media.live_info}
                                {@const info = media.live_info as any}
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
                                                        <h3 class="text-2xl font-bold text-text-primary tracking-tight">{info.drive?.vendor || 'Unknown'}</h3>
                                                        <span class="text-lg font-medium text-text-secondary opacity-40">{info.drive?.model || 'Generic LTO'}</span>
                                                    </div>
                                                    <StatusBadge variant="blue">
                                                        <div class="w-1.5 h-1.5 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)] animate-pulse"></div>
                                                        Online
                                                    </StatusBadge>
                                                </div>
                                                <div class="mt-2 flex items-center gap-4 text-xs font-mono text-text-secondary/60">
                                                    <span>FIRMWARE: <span class="text-text-primary">{info.drive?.firmware || 'N/A'}</span></span>
                                                    <span class="h-3 w-px bg-border-color"></span>
                                                    <span>DEVICE: <span class="text-text-primary">{media.config?.device_path || '/dev/nst0'}</span></span>
                                                </div>
                                            </div>

                                            <!-- Live Performance / Health Dashboard -->
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

                                            <div class="grid grid-cols-2 gap-8 pt-2">
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Assigned ID</span>
                                                    <span class="text-base font-bold text-text-primary mono">{media.identifier}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Load count</span>
                                                    <span class="text-base font-bold text-text-primary mono flex items-center gap-2">
                                                        <RotateCw size={14} class="text-blue-500 opacity-50" />
                                                        {info.tape?.load_count || '0'}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <!-- Media/MAM Info -->
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
                                                                <span>Used: {(used_mib / 1024).toFixed(1)} GiB</span>
                                                                <span>Free: {(info.tape.remaining_capacity_mib / 1024).toFixed(1)} GiB</span>
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
                                    </div>
                                </Card>
                            {/if}
                        {/each}
                    </div>
                </div>
            {/if}

            <!-- Active Media -->
            <div class="space-y-4">
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
                        <tbody
                            use:dndzone={{items: mediaList.filter(m => m.status === 'active' && (m.capacity === 0 || (m.bytes_used / m.capacity) < 0.98)), flipDurationMs: 200}}
                            onconsider={handleDndConsider}
                            onfinalize={handleDndFinalize}
                            class="divide-y divide-border-color/30"
                        >
                            {#each mediaList.filter(m => m.status === 'active' && (m.capacity === 0 || (m.bytes_used / m.capacity) < 0.98)) as media (media.id)}
                                <tr class="hover:bg-bg-primary/30 transition-colors group">
                                    <td class="px-6 py-4 text-center">
                                        <div class="cursor-grab active:cursor-grabbing text-text-secondary opacity-20 group-hover:opacity-100 transition-opacity">
                                            <GripVertical size={16} />
                                        </div>
                                    </td>
                                    {@render mediaRow(media)}
                                </tr>
                            {:else}
                                <tr><td colspan="8" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-medium">No active archive media</p></td></tr>
                            {/each}
                        </tbody>
                    </table>
                </Card>
            </div>

            <!-- Fully Utilized Media -->
            {#if mediaList.some(m => m.status === 'active' && m.capacity > 0 && (m.bytes_used / m.capacity) >= 0.98)}
                <div class="space-y-4">
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
                                {#each mediaList.filter(m => m.status === 'active' && m.capacity > 0 && (m.bytes_used / m.capacity) >= 0.98) as media (media.id)}
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
            {#if mediaList.some(m => m.status !== 'active')}
                <div class="space-y-4">
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
                                {#each mediaList.filter(m => m.status !== 'active') as media (media.id)}
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

            <div class="grid grid-cols-3 gap-4">
                {#each providersList as provider}
                    <button class={cn("flex flex-col items-center gap-3 p-4 rounded-xl border-2 transition-all", newMedia.media_type === provider.provider_id ? "bg-blue-500/10 border-blue-500 text-blue-400 shadow-lg shadow-blue-500/10" : "bg-bg-primary/50 border-border-color text-text-secondary hover:border-text-secondary/30")}
                        onclick={() => {
                            newMedia.media_type = provider.provider_id;
                            if (provider.provider_id === 'lto_tape') newMedia.location = 'Storage Shelf';
                            else if (provider.provider_id === 'local_hdd') newMedia.location = 'Offsite Safe';
                            else newMedia.location = 'Cloud';
                        }}
                    >
                        {@render ConfigIcon(provider.provider_id)}
                        <span class="text-xs font-semibold">{provider.name}</span>
                    </button>
                {/each}
            </div>

            <div class="space-y-6">
                <div class="grid grid-cols-2 gap-6">
                    <div class="space-y-2">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="identifier">Identifier (Barcode/SN)</label>
                        <Input id="identifier" bind:value={newMedia.identifier} placeholder="BUP-00001" class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                    </div>
                    <div class="space-y-2">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="capacity">Capacity (GB)</label>
                        <Input id="capacity" type="number" bind:value={newMedia.capacity_gb} class="h-10 bg-bg-primary/50 border-border-color font-mono" />
                        <p class="text-[10px] text-text-secondary leading-tight opacity-60">Auto-detected when possible. You can manually reduce this to reserve space.</p>
                    </div>
                </div>

                <div class="space-y-2">
                    <label class="text-xs font-medium text-text-secondary ml-1" for="location">Physical location</label>
                    <div class="relative">
                        <MapPin size={16} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                        <Input id="location" bind:value={newMedia.location} placeholder="Cabinet A, Shelf 2" class="h-10 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                    </div>
                </div>

                <!-- Dynamic Provider Config Fields -->
                {#if activeProvider}
                    <div class="grid grid-cols-2 gap-4 animate-in slide-in-from-top-2 duration-300">
                        {#each Object.entries(activeProvider.config_schema) as [key, schema]}
                            {@const field = schema as any}
                            <div class="space-y-2 flex flex-col justify-center">
                                {#if field.type === 'boolean'}
                                    <div class="flex items-center gap-3 h-10 px-1">
                                        <input
                                            id="config-{key}"
                                            type="checkbox"
                                            bind:checked={dynamicConfig[key]}
                                            class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20"
                                        />
                                        <label class="text-xs font-medium text-text-secondary cursor-pointer" for="config-{key}">{field.title || key}</label>
                                    </div>
                                {:else}
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="config-{key}">{field.title || key}</label>
                                    <Input
                                        id="config-{key}"
                                        bind:value={dynamicConfig[key]}
                                        placeholder={field.description || ""}
                                        type={key.includes("key") || key.includes("passphrase") ? "password" : "text"}
                                        class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm"
                                    />
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
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
                            <span class="text-xs text-text-secondary block opacity-60">{editingMedia.media_type} &bull; {editingMedia.generation_tier}</span>
                        </div>
                    </div>

                    <div class="space-y-2 animate-in fade-in duration-300">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="edit-location">Physical location</label>
                        <Input id="edit-location" bind:value={editingMedia.location} class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm" />
                    </div>

                    <!-- Dynamic Config for Edit -->
                    {#if providersList.find(p => p.provider_id === editingMedia?.media_type)}
                        {@const schema = providersList.find(p => p.provider_id === editingMedia?.media_type)?.config_schema || {}}
                        <div class="grid grid-cols-1 gap-4">
                            {#each Object.entries(schema) as [key, entry]}
                                {@const field = entry as any}
                                <div class="space-y-2 flex flex-col justify-center">
                                    {#if field.type === 'boolean'}
                                        <div class="flex items-center gap-3 h-10 px-1">
                                            <input
                                                id="edit-config-{key}"
                                                type="checkbox"
                                                bind:checked={(editingMedia.config[key] as any)}
                                                class="w-4 h-4 rounded border-border-color bg-bg-primary text-blue-600 focus:ring-blue-500/20"
                                            />
                                            <label class="text-xs font-medium text-text-secondary cursor-pointer" for="edit-config-{key}">{field.title || key}</label>
                                        </div>
                                    {:else}
                                        <label class="text-xs font-medium text-text-secondary ml-1" for="edit-config-{key}">{field.title || key}</label>
                                        <Input
                                            id="edit-config-{key}"
                                            bind:value={editingMedia.config[key]}
                                            type={key.includes("key") || key.includes("passphrase") ? "password" : "text"}
                                            class="h-10 bg-bg-primary/50 border-border-color font-mono text-sm"
                                        />
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <label class="text-xs font-medium text-text-secondary ml-1" for="edit-status">Status</label>
                        <select
                            id="edit-status"
                            bind:value={editingMedia.status}
                            class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer"
                        >
                            <option value="active">Active</option>
                            <option value="retired">Retired</option>
                            <option value="failed">Hardware Failure</option>
                        </select>
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
</div>
