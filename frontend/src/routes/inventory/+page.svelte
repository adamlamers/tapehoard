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
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import { cn } from '$lib/utils';
    import {
        listStorageFleetInventoryMediaGet,
        registerNewMediaInventoryMediaPost,
        deleteMediaAssetInventoryMediaMediaIdDelete,
        triggerBackupJobBackupsTriggerMediaIdPost,
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

    onMount(async () => {
        // Initial load (non-silent and forced refresh to show live hardware status immediately)
        loadMedia(false, true);

        try {
            const res = await listStorageProvidersInventoryProvidersGet();
            if (res.data) providersList = res.data;
        } catch (error) {
            console.error("Failed to load storage providers:", error);
        }

        pollInterval = setInterval(() => loadMedia(true), 5000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    function handleDndConsider(e: CustomEvent) {
        const activeItems = e.detail.items;
        const inactiveItems = mediaList.filter(m => m.status !== 'active');
        mediaList = [...activeItems, ...inactiveItems];
    }

    async function handleDndFinalize(e: CustomEvent) {
        const activeItems = e.detail.items;
        const inactiveItems = mediaList.filter(m => m.status !== 'active');
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
    <td class="px-6 py-4">
        {#if media.status === 'active' && mediaList.filter(m => m.status === 'active')[0]?.id === media.id}
             <div class="flex items-center gap-2">
                <Star size={12} class="text-yellow-500" fill="currentColor" />
                <span class="text-[10px] font-black text-yellow-500/80 uppercase tracking-tighter">Priority 1</span>
            </div>
        {:else}
            <span class="text-[10px] font-bold text-text-secondary opacity-20 mono">#{media.priority_index}</span>
        {/if}
    </td>
    <td class="px-2 py-4">
        <div class="flex justify-center">
            {#if media.is_online}
                {#if media.is_identified}
                    <div class="w-2.5 h-2.5 rounded-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.6)]" title="Hardware Verified & Online"></div>
                {:else}
                    <div class="w-2.5 h-2.5 rounded-full bg-orange-500 shadow-[0_0_10px_rgba(249,115,22,0.6)] animate-pulse" title="Hardware Present but Uninitialized"></div>
                {/if}
            {:else}
                <div class="w-2.5 h-2.5 rounded-full bg-text-secondary/10 border border-text-secondary/20" title="Offline"></div>
            {/if}
        </div>
    </td>
    <td class="px-6 py-4">
        <div class="flex flex-col min-w-0">
            <span class="text-xs font-black text-text-primary uppercase tracking-widest truncate">{media.identifier}</span>
            <div class="mt-1 flex flex-col gap-1">
                {#if (media.media_type === 'local_hdd' || media.media_type === 'hdd') && media.config?.mount_path}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[9px] font-mono truncate">
                        <Monitor size={10} /> {media.config.mount_path}
                    </div>
                {:else if media.media_type === 's3_compat' && media.config?.bucket_name}
                    <div class="flex items-center gap-1.5 text-text-secondary/50 text-[9px] font-mono truncate">
                        <Globe size={10} /> {media.config.bucket_name}
                    </div>
                {/if}
                <div class="flex gap-2 mt-0.5">
                    {#if media.status === 'failed'}
                        <span class="text-[8px] font-black uppercase tracking-tighter text-error-color bg-error-color/10 px-1 rounded border border-error-color/20">HARDWARE FAILURE</span>
                    {:else if media.status === 'retired'}
                        <span class="text-[8px] font-black uppercase tracking-tighter text-text-secondary bg-bg-primary px-1 rounded border border-border-color">RETIRED</span>
                    {/if}

                    {#if media.config?.encryption_key || media.config?.encryption_passphrase}
                        <span class="text-[8px] font-black uppercase tracking-tighter text-blue-400 bg-blue-500/10 px-1 rounded flex items-center gap-1 border border-blue-500/20">
                            <ShieldCheck size={8} /> ENCRYPTED
                        </span>
                    {/if}
                </div>
            </div>
        </div>
    </td>
    <td class="px-6 py-4">
        <div class="flex flex-col">
            <span class="text-[10px] font-bold uppercase text-text-secondary">{media.media_type}</span>
            <div class="flex items-center gap-2 mt-1">
                <span class="text-[10px] font-medium text-text-secondary/40">{media.generation_tier || 'Generic'}</span>
                {#if (media.media_type === 'local_hdd' || media.media_type === 'hdd') && media.config?.device_uuid}
                    <span class="text-[9px] font-mono text-text-secondary/30 truncate max-w-[80px]">{media.config.device_uuid}</span>
                {/if}
            </div>
        </div>
    </td>
    <td class="px-6 py-4">
        <div class="flex items-center gap-1.5 text-text-secondary">
            <MapPin size={12} class="opacity-40" />
            <span class="text-[11px] font-bold uppercase tracking-tight">{media.location || 'Unknown'}</span>
        </div>
    </td>
    <td class="px-6 py-4">
        <div class="flex flex-col w-32 gap-1.5">
            <div class="flex justify-between items-end text-[10px]">
                <span class="font-black text-text-primary mono">{formatSize(media.bytes_used)}</span>
                <span class="text-text-secondary opacity-40 font-bold tracking-tighter uppercase">{Math.round((media.bytes_used / media.capacity) * 100)}%</span>
            </div>
            <div class="h-1.5 bg-bg-primary rounded-full overflow-hidden border border-border-color/30 flex">
                <div class="h-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.4)]" style="width: {(media.bytes_used / media.capacity) * 100}%"></div>
            </div>
            <span class="text-[8px] text-text-secondary opacity-30 font-bold uppercase tracking-widest text-right">CAP: {formatSize(media.capacity)}</span>
        </div>
    </td>
    <td class="px-6 py-4 text-right">
        <div class="flex justify-end gap-1">
            {#if media.is_online}
                {#if !media.is_identified}
                    <Button variant="outline" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest border-orange-500/30 text-orange-400 hover:bg-orange-500/10" onclick={() => handleInitialize(media.id, media.identifier)}>Initialize</Button>
                {:else if media.status === 'active'}
                    <Button variant="default" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest bg-blue-600 hover:bg-blue-500" onclick={() => handleStartBackup(media.id, media.identifier)}>Archive</Button>
                {/if}
            {/if}
            <Button variant="ghost" size="icon" class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5" onclick={() => openEdit(media)}><Edit3 size={14} /></Button>
            <Button variant="ghost" size="icon" class="h-8 w-8 text-text-secondary hover:text-error-color hover:bg-error-color/10" onclick={() => handleDelete(media.id)}><Trash2 size={14} /></Button>
        </div>
    </td>
{/snippet}

<svelte:head>
    <title>Media Inventory - TapeHoard</title>
</svelte:head>

<div class="flex flex-col h-full gap-8 animate-in fade-in duration-700 overflow-y-auto p-1">
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-6 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Library class="text-blue-500" size={28} />
                Physical Inventory
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Fleet Management & Hardware Status
            </p>
        </div>

        <div class="flex items-center gap-4 relative z-10">
            <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px] shadow-lg shadow-blue-500/10" onclick={() => showRegisterDialog = true}>
                <Plus size={18} class="mr-2" /> Register New Media
            </Button>
        </div>
    </header>

    <div class="space-y-12">
        <!-- DISCOVERED HARDWARE SECTION -->
        {#if filteredDiscoveredAssets.length > 0}
            <section class="space-y-6">
                <div class="flex items-center gap-3 px-2">
                    <div class="p-1.5 bg-action-color/10 rounded-md text-action-color"><Cpu size={16} /></div>
                    <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary">Discovered Unregistered Drives</h2>
                    <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {#each filteredDiscoveredAssets as asset}
                        <Card class="p-5 bg-bg-secondary border-dashed border-2 border-border-color hover:border-action-color/50 transition-all group">
                            <div class="flex items-start gap-4">
                                <div class="p-3 bg-action-color/10 rounded-xl text-action-color border border-action-color/20">
                                    {@render ConfigIcon(asset.type === 'tape' ? 'lto_tape' : 'local_hdd')}
                                </div>
                                <div class="flex-1 min-w-0">
                                    <h3 class="text-sm font-black text-text-primary uppercase tracking-tight truncate">{asset.identifier}</h3>
                                    <div class="flex items-center gap-1.5 mt-0.5 opacity-60">
                                        <Cpu size={10} class="text-action-color" />
                                        <span class="text-[9px] text-text-secondary font-black uppercase tracking-widest truncate mono">
                                            {#if asset.type === 'tape'}
                                                {asset.device_path}
                                            {:else}
                                                {asset.mount_path}
                                            {/if}
                                        </span>
                                    </div>

                                    {#if asset.type === 'tape' && asset.hardware_info}
                                        <div class="mt-3 space-y-2 border-t border-border-color/30 pt-3">
                                            {#if asset.hardware_info.drive}
                                                <div class="text-[8px] font-bold text-blue-400/80 uppercase">
                                                    Drive: {asset.hardware_info.drive.vendor} {asset.hardware_info.drive.model} ({asset.hardware_info.drive.firmware})
                                                </div>
                                            {/if}
                                            {#if asset.hardware_info.tape}
                                                <div class="flex flex-wrap gap-1">
                                                    <span class="text-[7px] font-black bg-white/5 px-1.5 py-0.5 rounded border border-white/10 text-text-secondary uppercase">MFR: {asset.hardware_info.tape.manufacturer}</span>
                                                    <span class="text-[7px] font-black bg-blue-500/10 px-1 rounded border border-blue-500/20 text-blue-400 uppercase">{asset.hardware_info.tape.generation_label || asset.hardware_info.tape.generation}</span>
                                                </div>
                                            {/if}
                                        </div>
                                    {/if}

                                    <div class="mt-4 flex gap-2">
                                        <Button variant="default" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest flex-1" onclick={() => {
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
                                        }}>Add Media</Button>
                                        <Button variant="outline" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest border-border-color/60 text-text-secondary hover:bg-white/5" onclick={() => handleIgnoreAsset(asset.identifier)}>Ignore</Button>
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
                <div class="space-y-6">
                    <div class="flex items-center gap-3 px-2">
                        <div class="p-1.5 bg-blue-500/10 rounded-md text-blue-500"><Cpu size={16} /></div>
                        <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary">Live Hardware Status</h2>
                        <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
                    </div>

                    <div class="grid grid-cols-1 gap-6">
                        {#each mediaList.filter(m => m.is_online && (m.media_type === 'lto_tape' || m.media_type === 'tape')) as media}
                            {#if media.live_info}
                                {@const info = media.live_info as any}
                                <Card class="bg-bg-secondary border-blue-500/30 shadow-2xl relative overflow-hidden">
                                    <div class="p-8 flex flex-col lg:flex-row gap-12">
                                        <!-- Drive Info -->
                                        <div class="flex-1 space-y-6">
                                            <div>
                                                <div class="text-[9px] font-black uppercase tracking-[0.2em] text-text-secondary opacity-50 mb-3 flex items-center gap-2">
                                                    <Cpu size={12} /> Physical Tape Drive
                                                </div>
                                                <div class="flex items-center gap-4">
                                                    <div class="flex items-baseline gap-3">
                                                        <h3 class="text-3xl font-black text-text-primary tracking-tighter uppercase">{info.drive?.vendor || 'Unknown'}</h3>
                                                        <span class="text-xl font-bold text-text-secondary opacity-40">{info.drive?.model || 'Generic LTO'}</span>
                                                    </div>
                                                    <div class="flex items-center gap-2 px-3 py-1 bg-blue-500/10 rounded-full border border-blue-500/20">
                                                        <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)] animate-pulse"></div>
                                                        <span class="text-[9px] font-black uppercase tracking-widest text-blue-400">Drive Online</span>
                                                    </div>
                                                </div>
                                                <div class="mt-2 flex items-center gap-4 text-[10px] font-mono text-text-secondary/60">
                                                    <span>FIRMWARE: <span class="text-text-primary font-bold">{info.drive?.firmware || 'N/A'}</span></span>
                                                    <span class="h-3 w-px bg-border-color"></span>
                                                    <span>DEVICE: <span class="text-text-primary font-bold">{media.config?.device_path || '/dev/nst0'}</span></span>
                                                </div>
                                            </div>

                                            <!-- Live Performance / Health Dashboard -->
                                            <div class="grid grid-cols-2 gap-4 pt-6 border-t border-border-color/30">
                                                <div class="bg-bg-primary/50 p-4 rounded-xl border border-border-color/50">
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-2">Session Performance</span>
                                                    <div class="space-y-3">
                                                        <div class="flex justify-between items-center text-[10px]">
                                                            <span class="text-text-secondary font-bold uppercase tracking-tighter flex items-center gap-1.5"><ArrowUp size={10} class="text-blue-400" /> WRITTEN</span>
                                                            <span class="text-text-primary font-black mono">{(info.tape?.session_mib_written || 0).toLocaleString()} MiB</span>
                                                        </div>
                                                        <div class="flex justify-between items-center text-[10px]">
                                                            <span class="text-text-secondary font-bold uppercase tracking-tighter flex items-center gap-1.5"><ArrowDown size={10} class="text-success-color" /> READ</span>
                                                            <span class="text-text-primary font-black mono">{(info.tape?.session_mib_read || 0).toLocaleString()} MiB</span>
                                                        </div>
                                                    </div>
                                                </div>

                                                <div class="bg-bg-primary/50 p-4 rounded-xl border border-border-color/50">
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-2">Hardware Health</span>
                                                    {#if info.tape?.alerts && info.tape.alerts.length > 0}
                                                        <div class="space-y-1">
                                                            {#each info.tape.alerts as alert}
                                                                <div class="flex items-center gap-2 text-[9px] font-black text-orange-400 uppercase tracking-tighter">
                                                                    <ShieldAlert size={10} /> {alert}
                                                                </div>
                                                            {/each}
                                                        </div>
                                                    {:else}
                                                        <div class="flex items-center gap-2 text-[10px] font-black text-success-color uppercase tracking-tighter">
                                                            <ShieldCheck size={14} /> System Healthy
                                                        </div>
                                                        <span class="text-[8px] text-text-secondary opacity-40 uppercase font-bold block mt-1">No active TapeAlerts</span>
                                                    {/if}
                                                </div>
                                            </div>

                                            <div class="grid grid-cols-2 gap-8 pt-4">
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Assigned ID</span>
                                                    <span class="text-lg font-black text-text-primary mono tracking-tighter">{media.identifier}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Load Count</span>
                                                    <span class="text-lg font-black text-text-primary mono tracking-tighter flex items-center gap-2">
                                                        <RotateCw size={14} class="text-blue-500 opacity-50" />
                                                        {info.tape?.load_count || '0'}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <!-- Media/MAM Info -->
                                        <div class="flex-1 bg-bg-primary/30 rounded-2xl p-6 border border-border-color/50 relative">
                                            <div class="text-[9px] font-black uppercase tracking-[0.2em] text-text-secondary opacity-50 mb-6 flex items-center justify-between">
                                                <div class="flex items-center gap-2"><Database size={12} /> Medium Metadata (MAM)</div>
                                                <span class="text-blue-400 font-black tracking-widest font-mono">{info.tape?.barcode || 'NO BARCODE'}</span>
                                            </div>

                                            <div class="grid grid-cols-2 gap-y-6 gap-x-12">
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Manufacturer</span>
                                                    <span class="text-xs font-bold text-text-primary uppercase tracking-wider">{info.tape?.manufacturer || 'Unknown'}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Media Serial</span>
                                                    <span class="text-xs font-bold text-text-primary mono">{info.tape?.serial || 'N/A'}</span>
                                                </div>
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">LTO Generation</span>
                                                    <span class="inline-flex items-center px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[10px] font-black border border-blue-500/20">
                                                        {info.tape?.generation_label || info.tape?.generation || 'LTO'}
                                                    </span>
                                                </div>
                                                <div>
                                                    <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Manufacture Date</span>
                                                    <span class="text-xs font-bold text-text-primary mono">{info.tape?.manufacture_date || 'N/A'}</span>
                                                </div>

                                                <div class="col-span-2 space-y-4 pt-2">
                                                    <!-- Capacity Utilization -->
                                                    {#if info.tape?.remaining_capacity_mib !== undefined && info.tape?.max_capacity_mib}
                                                        {@const used_mib = info.tape.max_capacity_mib - info.tape.remaining_capacity_mib}
                                                        {@const perc = Math.min(100, Math.round((used_mib / info.tape.max_capacity_mib) * 100))}
                                                        <div>
                                                            <div class="flex justify-between items-end mb-2">
                                                                <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40">Physical Capacity Utilization</span>
                                                                <span class="text-[10px] font-black text-blue-400 mono">{perc}%</span>
                                                            </div>
                                                            <div class="h-2 bg-bg-primary rounded-full overflow-hidden border border-border-color/30 flex">
                                                                <div class="h-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)] transition-all duration-1000" style="width: {perc}%"></div>
                                                            </div>
                                                            <div class="flex justify-between mt-1 text-[8px] font-bold text-text-secondary/50 mono uppercase">
                                                                <span>Used: {(used_mib / 1024).toFixed(1)} GiB</span>
                                                                <span>Free: {(info.tape.remaining_capacity_mib / 1024).toFixed(1)} GiB</span>
                                                            </div>
                                                        </div>
                                                    {/if}

                                                    <div>
                                                        <span class="text-[8px] font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Inserted Tape Identifier</span>
                                                        <div class="bg-bg-secondary p-3 rounded-lg border border-border-color font-mono text-xs text-text-primary italic shadow-inner">
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
            <div class="space-y-6">
                <div class="flex items-center gap-3 px-2">
                    <div class="p-1.5 bg-blue-500/10 rounded-md text-blue-500"><Database size={16} /></div>
                    <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary">Active Archive Media</h2>
                    <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
                </div>

                <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden flex flex-col">
                    <div class="px-6 py-3 bg-bg-tertiary/30 border-b border-border-color flex items-center justify-end gap-6">
                        <div class="flex items-center gap-2">
                            <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
                            <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-70">Identified & Online</span>
                        </div>
                        <div class="h-4 w-px bg-border-color mx-2"></div>
                        <div class="flex items-center gap-2">
                            <Star size={10} class="text-yellow-500" fill="currentColor" />
                            <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-70">Next Archival Target</span>
                        </div>
                    </div>

                    <table class="w-full border-collapse">
                        <thead>
                            <tr class="bg-bg-tertiary/50 border-b border-border-color">
                                <th class="px-6 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary">DRAG</th>
                                <th class="px-6 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary">#</th>
                                <th class="px-2 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary">Stat</th>
                                <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Identity</th>
                                <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Type & Tier</th>
                                <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Location</th>
                                <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Utilization</th>
                                <th class="px-6 py-4 text-right text-[10px] font-black uppercase tracking-widest text-text-secondary">Actions</th>
                            </tr>
                        </thead>
                        <tbody
                            use:dndzone={{items: mediaList.filter(m => m.status === 'active'), flipDurationMs: 200}}
                            onconsider={handleDndConsider}
                            onfinalize={handleDndFinalize}
                            class="divide-y divide-border-color/30"
                        >
                            {#each mediaList.filter(m => m.status === 'active') as media (media.id)}
                                <tr class="hover:bg-bg-primary/30 transition-colors group">
                                    <td class="px-6 py-4 text-center">
                                        <div class="cursor-grab active:cursor-grabbing text-text-secondary opacity-20 group-hover:opacity-100 transition-opacity">
                                            <GripVertical size={16} />
                                        </div>
                                    </td>
                                    {@render mediaRow(media)}
                                </tr>
                            {:else}
                                <tr><td colspan="8" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-black uppercase tracking-[0.2em]">No Active Archive Media</p></td></tr>
                            {/each}
                        </tbody>
                    </table>
                </Card>
            </div>

            <!-- Retired & Failed Media -->
            {#if mediaList.some(m => m.status !== 'active')}
                <div class="space-y-6">
                    <div class="flex items-center gap-3 px-2">
                        <div class="p-1.5 bg-error-color/10 rounded-md text-error-color"><ShieldAlert size={16} /></div>
                        <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary opacity-60">Retired & Failed Media</h2>
                        <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent opacity-30"></div>
                    </div>

                    <Card class="bg-bg-secondary/60 border border-border-color/60 rounded-xl overflow-hidden shadow-xl grayscale-[0.5] opacity-80">
                        <table class="w-full border-collapse">
                            <thead>
                                <tr class="bg-bg-tertiary/20 border-b border-border-color/40">
                                    <th class="px-6 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">SORT</th>
                                    <th class="px-6 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">#</th>
                                    <th class="px-2 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Stat</th>
                                    <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Identity</th>
                                    <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Type & Tier</th>
                                    <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Location</th>
                                    <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Utilization</th>
                                    <th class="px-6 py-4 text-right text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Actions</th>
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
    {#if showRegisterDialog}
        <div class="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-6" onmousedown={() => showRegisterDialog = false}>
            <Card class="w-[700px] max-h-[90vh] overflow-y-auto bg-bg-secondary border-border-color shadow-2xl p-10 flex flex-col gap-8 animate-in zoom-in-95 duration-300" onmousedown={(e) => e.stopPropagation()}>
                <header class="flex justify-between items-start">
                    <div>
                        <h2 class="text-2xl font-black text-text-primary uppercase tracking-tighter">Add New Media</h2>
                        <p class="text-[11px] font-bold text-text-secondary uppercase tracking-widest mt-1 opacity-60">Add physical storage locations for your backups.</p>
                    </div>
                    <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => showRegisterDialog = false}><X size={24} /></Button>
                </header>

                <div class="grid grid-cols-3 gap-4">
                    {#each providersList as provider}
                        <button class={cn("flex flex-col items-center gap-3 p-4 rounded-xl border-2 transition-all", newMedia.media_type === provider.provider_id ? "bg-blue-500/10 border-blue-500 text-blue-400 shadow-[0_0_20px_rgba(59,130,246,0.15)]" : "bg-bg-primary/50 border-border-color text-text-secondary hover:border-text-secondary/30")}
                            onclick={() => {
                                newMedia.media_type = provider.provider_id;
                                if (provider.provider_id === 'lto_tape') newMedia.location = 'Storage Shelf';
                                else if (provider.provider_id === 'local_hdd') newMedia.location = 'Offsite Safe';
                                else newMedia.location = 'Cloud';
                            }}
                        >
                            {@render ConfigIcon(provider.provider_id)}
                            <span class="text-[10px] font-black uppercase tracking-widest">{provider.name}</span>
                        </button>
                    {/each}
                </div>

                <div class="space-y-6">
                    <div class="grid grid-cols-2 gap-6">
                        <div class="space-y-2">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="identifier">Identifier (Barcode/SN)</label>
                            <Input id="identifier" bind:value={newMedia.identifier} placeholder="BUP-00001" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                        </div>
                        <div class="space-y-2">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="capacity">Capacity (GB)</label>
                            <Input id="capacity" type="number" bind:value={newMedia.capacity_gb} class="h-12 bg-bg-primary/50 border-border-color font-mono" />
                            <p class="text-[9px] text-text-secondary leading-tight opacity-60">Auto-detected when possible. You can manually reduce this to reserve space.</p>
                        </div>
                    </div>

                    <div class="space-y-2">
                        <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="location">Physical Location</label>
                        <div class="relative">
                            <MapPin size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                            <Input id="location" bind:value={newMedia.location} placeholder="Cabinet A, Shelf 2" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                        </div>
                    </div>

                    <!-- Dynamic Provider Config Fields -->
                    {#if activeProvider}
                        <div class="grid grid-cols-2 gap-4 animate-in slide-in-from-top-2 duration-300">
                            {#each Object.entries(activeProvider.config_schema) as [key, schema]}
                                {@const field = schema as any}
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="config-{key}">{field.title || key}</label>
                                    <Input
                                        id="config-{key}"
                                        bind:value={dynamicConfig[key]}
                                        placeholder={field.description || ""}
                                        type={key.includes("key") || key.includes("passphrase") ? "password" : "text"}
                                        class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm"
                                    />
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>

                <footer class="flex gap-3 pt-4 border-t border-border-color">
                    <Button variant="outline" class="flex-1 h-12 font-black uppercase tracking-widest text-[11px]" onclick={() => showRegisterDialog = false}>Cancel</Button>
                    <Button variant="default" class="flex-[2] h-12 font-black uppercase tracking-widest text-[11px]" onclick={handleRegister}>Register Media</Button>
                </footer>
            </Card>
        </div>
    {/if}

    <!-- Edit Dialog -->
    {#if editingMedia}
        <div class="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-6" onmousedown={() => editingMedia = null}>
            <Card class="w-[600px] max-h-[90vh] overflow-y-auto bg-bg-secondary border-border-color shadow-2xl p-10 flex flex-col gap-8 animate-in zoom-in-95 duration-300" onmousedown={(e) => e.stopPropagation()}>
                <header class="flex justify-between items-start">
                    <div>
                        <h2 class="text-2xl font-black text-text-primary uppercase tracking-tighter flex items-center gap-3">
                            <Edit3 size={24} class="text-blue-500" />
                            Edit Media Config
                        </h2>
                        <p class="text-[11px] font-bold text-text-secondary uppercase tracking-widest mt-1 opacity-60">Update hardware paths and physical location.</p>
                    </div>
                    <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => editingMedia = null}><X size={24} /></Button>
                </header>

                <div class="space-y-6">
                    <div class="p-4 bg-bg-primary/50 border border-border-color rounded-xl flex items-center gap-4">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 shrink-0">
                            {@render ConfigIcon(editingMedia.media_type)}
                        </div>
                        <div>
                            <span class="text-xs font-black text-text-primary uppercase tracking-widest">{editingMedia.identifier}</span>
                            <span class="text-[10px] text-text-secondary block opacity-60 uppercase">{editingMedia.media_type} &bull; {editingMedia.generation_tier}</span>
                        </div>
                    </div>

                    <div class="space-y-2 animate-in fade-in duration-300">
                        <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-location">Physical Location</label>
                        <Input id="edit-location" bind:value={editingMedia.location} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                    </div>

                    <!-- Dynamic Config for Edit -->
                    {#if providersList.find(p => p.provider_id === editingMedia?.media_type)}
                        {@const schema = providersList.find(p => p.provider_id === editingMedia?.media_type)?.config_schema || {}}
                        <div class="grid grid-cols-1 gap-4">
                            {#each Object.entries(schema) as [key, entry]}
                                {@const field = entry as any}
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-config-{key}">{field.title || key}</label>
                                    <Input
                                        id="edit-config-{key}"
                                        bind:value={editingMedia.config[key]}
                                        type={key.includes("key") || key.includes("passphrase") ? "password" : "text"}
                                        class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm"
                                    />
                                </div>
                            {/each}
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-status">Status</label>
                        <select
                            id="edit-status"
                            bind:value={editingMedia.status}
                            class="w-full h-12 bg-bg-primary border border-border-color rounded-xl px-4 text-sm font-bold text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer"
                        >
                            <option value="active">Active</option>
                            <option value="retired">Retired</option>
                            <option value="failed">Hardware Failure</option>
                        </select>
                    </div>
                </div>

                <footer class="flex gap-3 pt-4 border-t border-border-color">
                    <Button variant="outline" class="flex-1 h-12 font-black uppercase tracking-widest text-[11px]" onclick={() => editingMedia = null}>Cancel</Button>
                    <Button variant="default" class="flex-[2] h-12 font-black uppercase tracking-widest text-[11px]" onclick={handleUpdate}>
                        <Save size={18} class="mr-2" /> Save Changes
                    </Button>
                </footer>
            </Card>
        </div>
    {/if}
</div>
