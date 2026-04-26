<script lang="ts">
    import { onMount } from 'svelte';
    import {
        Plus,
        CassetteTape,
        HardDrive,
        Cloud,
        MapPin,
        Edit3,
        Database,
        ShieldCheck,
        RotateCw,
        Trash2,
        X,
        Save,
        Globe,
        Monitor,
        PlayCircle,
        Star,
        GripVertical,
        Cpu,
        AlertCircle
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import { cn } from '$lib/utils';
    import {
        listMediaInventoryMediaGet,
        registerMediaInventoryMediaPost,
        deleteMediaInventoryMediaMediaIdDelete,
        triggerBackupBackupsTriggerMediaIdPost,
        initializeMediaInventoryMediaMediaIdInitializePost,
        reorderMediaInventoryMediaReorderPost,
        updateMediaInventoryMediaMediaIdPatch,
        discoverHardwareSystemHardwareDiscoverGet,
        ignoreHardwareSystemHardwareIgnorePost,
        type MediaSchema
    } from '$lib/api';
    import { dndzone } from 'svelte-dnd-action';
    import { toast } from 'svelte-sonner';

    let mediaList = $state<MediaSchema[]>([]);
    let discoveredAssets = $state<any[]>([]);
    let loading = $state(true);
    let showRegisterDialog = $state(false);
    let showAdvancedCloud = $state(false);
    let editingMedia = $state<MediaSchema | null>(null);

    // New Media Form State
    let newMedia = $state({
        media_type: 'tape',
        identifier: '',
        generation_tier: 'LTO-6',
        capacity_gb: 2500,
        location: 'Storage Shelf',
        // Type-specific config
        encryption_key: '', // 256-bit Hex Key
        enable_encryption: false,
        mount_path: '', // For HDD
        bucket_name: '', // For Cloud
        cloud_provider: 'AWS S3',
        cloud_region: 'us-east-1',
        endpoint_url: '', // For Custom S3
        access_key: '',
        secret_key: '',
        encryption_passphrase: ''
    });

    async function loadMedia() {
        loading = true;
        try {
            const [mediaRes, hardwareRes] = await Promise.all([
                listMediaInventoryMediaGet(),
                discoverHardwareSystemHardwareDiscoverGet()
            ]);
            if (mediaRes.data) mediaList = mediaRes.data;
            if (hardwareRes.data) discoveredAssets = hardwareRes.data as any[];
        } catch (error) {
            toast.error("Failed to load inventory details");
        } finally {
            loading = false;
        }
    }

    function handleDndConsider(e: CustomEvent) {
        mediaList = e.detail.items;
    }

    async function handleDndFinalize(e: CustomEvent) {
        mediaList = e.detail.items;
        try {
            await reorderMediaInventoryMediaReorderPost({
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
            await initializeMediaInventoryMediaMediaIdInitializePost({
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

    async function handleStartBackup(mediaId: number, identifier: string) {        try {
            await triggerBackupBackupsTriggerMediaIdPost({
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

        const config: Record<string, any> = {};
        if (newMedia.media_type === 'tape') {
            if (newMedia.enable_encryption && newMedia.encryption_key) {
                config.encryption_key = newMedia.encryption_key;
            }
        } else if (newMedia.media_type === 'hdd') {
            if (!newMedia.mount_path) { toast.error("Mount path required"); return; }
            config.mount_path = newMedia.mount_path;
        } else if (newMedia.media_type === 'cloud') {
            if (!newMedia.bucket_name) { toast.error("Bucket name required"); return; }
            config.bucket_name = newMedia.bucket_name;
            config.provider = newMedia.cloud_provider;
            config.region = newMedia.cloud_region;
            config.endpoint_url = newMedia.endpoint_url;
            config.access_key = newMedia.access_key;
            config.secret_key = newMedia.secret_key;
            config.encryption_passphrase = newMedia.encryption_passphrase;
        }

        try {
            await registerMediaInventoryMediaPost({
                body: {
                    media_type: newMedia.media_type,
                    identifier: newMedia.identifier,
                    generation_tier: newMedia.generation_tier,
                    capacity: newMedia.capacity_gb * 1024 * 1024 * 1024,
                    location: newMedia.location,
                    config: config
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
            await updateMediaInventoryMediaMediaIdPatch({
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

    async function handleIgnore(identifier: string) {
        try {
            await ignoreHardwareSystemHardwareIgnorePost({
                body: { identifier },
                throwOnError: true
            });
            toast.info("Hardware ignored");
            loadMedia();
        } catch (error) {
            toast.error("Failed to ignore hardware");
        }
    }

    async function handleDelete(mediaId: number) {
        if (!confirm("Are you sure? This will remove the media and its entire version history from the system index.")) return;
        try {
            await deleteMediaInventoryMediaMediaIdDelete({
                path: { media_id: mediaId },
                throwOnError: true
            });
            toast.success("Media removed from inventory");
            loadMedia();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to delete media");
        }
    }

    function formatSize(bytes: number) {
        const gb = bytes / (1024 * 1024 * 1024);
        if (gb >= 1000) return `${(gb / 1024).toFixed(2)} TB`;
        return `${gb.toFixed(0)} GB`;
    }

    onMount(loadMedia);
</script>

<svelte:head>
    <title>Media Inventory - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <CassetteTape class="text-blue-500" size={28} />
                Media Inventory
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Physical Asset Management & Archival Targets
            </p>
        </div>

        <div class="flex items-center gap-3 z-10">
            <Button variant="outline" size="icon" class="h-12 w-12 border-border-color" onclick={loadMedia} disabled={loading}>
                <RotateCw size={20} class={loading ? 'animate-spin' : ''} />
            </Button>
            <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px]" onclick={() => showRegisterDialog = true}>
                <Plus size={18} class="mr-2" /> Register New Media
            </Button>
        </div>
    </header>

    <div class="space-y-10">
        <!-- DISCOVERED HARDWARE SECTION -->
        {#if discoveredAssets.length > 0}
            <section class="space-y-6">
                <div class="flex items-center gap-3 px-2">
                    <div class="p-1.5 bg-action-color/10 rounded-md text-action-color"><Cpu size={16} /></div>
                    <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary">Discovered Unregistered Hardware</h2>
                    <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {#each discoveredAssets as asset}
                        {#if !asset.is_registered}
                            <Card class="p-5 bg-bg-secondary border-dashed border-2 border-border-color hover:border-action-color/50 transition-all group">
                                <div class="flex items-start gap-4">
                                    <div class="p-3 bg-action-color/10 rounded-xl text-action-color border border-action-color/20">
                                        {#if asset.type === 'tape'}<CassetteTape size={24} />{:else}<HardDrive size={24} />{/if}
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
                                        <div class="mt-4 flex gap-2">
                                            <Button variant="default" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest flex-1" onclick={() => {
                                                newMedia.media_type = asset.type;
                                                newMedia.identifier = asset.identifier === 'Unrecognized Disk' ? '' : asset.identifier;
                                                if (asset.type === 'hdd') newMedia.mount_path = asset.mount_path;
                                                showRegisterDialog = true;
                                            }}>Ingest Asset</Button>
                                            <Button variant="outline" size="sm" class="h-8 text-[9px] font-black uppercase tracking-widest border-border-color/60 text-text-secondary hover:bg-white/5" onclick={() => handleIgnore(asset.type === 'tape' ? asset.identifier : asset.mount_path)}>Ignore</Button>
                                        </div>
                                    </div>
                                </div>
                            </Card>
                        {/if}
                    {/each}
                </div>
            </section>
        {/if}

        <!-- INVENTORY SECTION -->
        <section class="space-y-6">
            <div class="flex items-center gap-3 px-2">
                <div class="p-1.5 bg-blue-500/10 rounded-md text-blue-500"><Database size={16} /></div>
                <h2 class="text-[11px] font-black uppercase tracking-[0.2em] text-text-primary">Fleet Inventory</h2>
                <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
            </div>

            <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden flex flex-col">
                <!-- Table Legend -->
                <div class="px-6 py-3 bg-bg-tertiary/30 border-b border-border-color flex items-center justify-end gap-6">
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
                        <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-70">Identified & Online</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 rounded-full bg-orange-500 shadow-[0_0_8px_rgba(249,115,22,0.5)]"></div>
                        <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-70">Hardware Needs Initialization</span>
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
                            <th class="px-6 py-4 w-12"></th>
                            <th class="px-2 py-4 w-12 text-center text-[10px] font-black uppercase tracking-widest text-text-secondary">Stat</th>
                            <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Identity</th>
                            <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Type & Tier</th>
                            <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Location</th>
                            <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Utilization</th>
                            <th class="px-6 py-4 text-right text-[10px] font-black uppercase tracking-widest text-text-secondary">Actions</th>
                        </tr>
                    </thead>
                    <tbody
                        use:dndzone={{items: mediaList, flipDurationMs: 200}}
                        onconsider={handleDndConsider}
                        onfinalize={handleDndFinalize}
                        class="divide-y divide-border-color/30"
                    >
                        {#each mediaList as media (media.id)}
                            <tr class="hover:bg-bg-primary/30 transition-colors group">
                                <td class="px-6 py-4 text-center">
                                    <div class="cursor-grab active:cursor-grabbing text-text-secondary opacity-20 group-hover:opacity-100 transition-opacity">
                                        <GripVertical size={16} />
                                    </div>
                                </td>
                                <td class="px-2 py-4 text-center">
                                    <div class="flex justify-center">
                                        {#if media.is_online}
                                            {#if media.is_identified}
                                                <div class="w-2.5 h-2.5 rounded-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.6)] animate-pulse" title="Online & Verified"></div>
                                            {:else}
                                                <div class="w-2.5 h-2.5 rounded-full bg-orange-500 shadow-[0_0_10px_rgba(249,115,22,0.6)] animate-pulse" title="Hardware Present but Uninitialized"></div>
                                            {/if}
                                        {:else}
                                            <div class="w-2.5 h-2.5 rounded-full bg-white/5 border border-white/10" title="Offline"></div>
                                        {/if}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center gap-3">
                                        <div
                                            class={cn(
                                                "p-1.5 rounded border transition-all shrink-0",
                                                mediaList.indexOf(mediaList.find(m => m.id === media.id)!) === 0
                                                    ? "bg-yellow-500/10 border-yellow-500/40 text-yellow-500"
                                                    : "bg-transparent border-transparent text-text-secondary opacity-0"
                                            )}
                                        >
                                            <Star size={14} fill={mediaList.indexOf(mediaList.find(m => m.id === media.id)!) === 0 ? "currentColor" : "none"} />
                                        </div>
                                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 shrink-0">
                                            {#if media.media_type === 'tape'}<CassetteTape size={18} />{/if}
                                            {#if media.media_type === 'hdd'}<HardDrive size={18} />{/if}
                                            {#if media.media_type === 'cloud'}<Cloud size={18} />{/if}
                                        </div>
                                        <div>
                                            <div class="flex items-center gap-2">
                                                <span class="text-sm font-black text-text-primary mono tracking-tight">{media.identifier}</span>
                                                {#if mediaList.indexOf(mediaList.find(m => m.id === media.id)!) === 0}
                                                    <span class="text-[8px] font-black uppercase bg-yellow-500/10 text-yellow-500 px-1.5 py-0.5 rounded border border-yellow-500/20">Next Target</span>
                                                {/if}
                                            </div>
                                            <div class="flex gap-2 mt-0.5">
                                                {#if media.config?.encryption_key || media.config?.encryption_passphrase}
                                                    <span class="text-[8px] font-black uppercase tracking-tighter text-blue-400 bg-blue-500/10 px-1 rounded flex items-center gap-1">
                                                        <ShieldCheck size={8} /> ENCRYPTED
                                                    </span>
                                                {/if}
                                                {#if media.is_online && !media.is_identified}
                                                    <span class="text-[8px] font-black uppercase tracking-tighter text-orange-400 bg-orange-500/10 px-1 rounded flex items-center gap-1 border border-orange-500/20">
                                                        <AlertCircle size={8} /> UNINITIALIZED
                                                    </span>
                                                {/if}
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <span class="text-[10px] font-bold uppercase text-text-secondary">{media.media_type}</span>
                                    <span class="text-[10px] font-medium text-text-secondary/40 ml-2 border-l border-border-color pl-2">{media.generation_tier || 'Generic'}</span>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center gap-1.5 text-text-secondary">
                                        <MapPin size={12} class="opacity-40" />
                                        <span class="text-[11px] font-bold uppercase tracking-tight">{media.location || 'Unknown'}</span>
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="w-32 space-y-1.5">
                                        <div class="flex justify-between text-[9px] font-black mono text-text-secondary uppercase">
                                            <span>{formatSize(media.bytes_used)}</span>
                                            <span class="opacity-40">/ {formatSize(media.capacity)}</span>
                                        </div>
                                        <div class="w-full bg-bg-primary h-1.5 rounded-full border border-border-color overflow-hidden">
                                            <div class="bg-blue-500 h-full transition-all duration-1000" style="width: {(media.bytes_used / media.capacity) * 100}%"></div>
                                        </div>
                                    </div>
                                </td>
                                <td class="px-6 py-4 text-right">
                                    <div class="flex items-center justify-end gap-2">
                                        {#if media.status === 'active'}
                                            <Button
                                                variant="secondary"
                                                size="sm"
                                                class="h-9 px-4 font-black uppercase tracking-widest text-[9px] border-action-color/30 text-action-color hover:bg-action-color/10"
                                                onclick={() => handleInitialize(media.id, media.identifier)}
                                                disabled={!media.is_online}
                                            >
                                                <RotateCw size={14} class="mr-1.5" /> Initialize
                                            </Button>
                                            <Button
                                                variant="secondary"
                                                size="sm"
                                                class="h-9 px-4 font-black uppercase tracking-widest text-[9px] border-success-color/30 text-success-color hover:bg-success-color/10"
                                                onclick={() => handleStartBackup(media.id, media.identifier)}
                                                disabled={!media.is_online || !media.is_identified}
                                            >
                                                <PlayCircle size={14} class="mr-1.5" /> Archive
                                            </Button>
                                        {/if}
                                        <Button variant="ghost" size="icon" class="h-9 w-9 hover:bg-white/10" onclick={() => openEdit(media)} title="Edit Configuration"><Edit3 size={16} /></Button>
                                        <Button variant="ghost" size="icon" class="h-9 w-9 hover:bg-error-color/10 hover:text-error-color" onclick={() => handleDelete(media.id)} title="Delete Media"><Trash2 size={16} /></Button>
                                    </div>
                                </td>
                            </tr>
                        {:else}
                            <tr><td colspan="8" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-black uppercase tracking-[0.2em]">No Media Assets Registered</p></td></tr>
                        {/each}
                    </tbody>
                </table>
            </Card>
        </section>
    </div>

    <!-- Registration Dialog -->
    {#if showRegisterDialog}
        <div class="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-6" onmousedown={() => showRegisterDialog = false}>
            <Card class="w-[700px] max-h-[90vh] overflow-y-auto bg-bg-secondary border-border-color shadow-2xl p-10 flex flex-col gap-8 animate-in zoom-in-95 duration-300" onmousedown={(e) => e.stopPropagation()}>
                <header class="flex justify-between items-start">
                    <div>
                        <h2 class="text-2xl font-black text-text-primary uppercase tracking-tighter">Register Fleet Asset</h2>
                        <p class="text-[11px] font-bold text-text-secondary uppercase tracking-widest mt-1 opacity-60">Provisioning physical storage for the unified index.</p>
                    </div>
                    <Button variant="ghost" size="icon" class="hover:bg-white/5" onclick={() => showRegisterDialog = false}><X size={24} /></Button>
                </header>

                <div class="grid grid-cols-3 gap-4">
                    {#each ['tape', 'hdd', 'cloud'] as type}
                        <button class={cn("flex flex-col items-center gap-3 p-4 rounded-xl border-2 transition-all", newMedia.media_type === type ? "bg-blue-500/10 border-blue-500 text-blue-400 shadow-[0_0_20px_rgba(59,130,246,0.15)]" : "bg-bg-primary/50 border-border-color text-text-secondary hover:border-text-secondary/30")} onclick={() => newMedia.media_type = type}>
                            {#if type === 'tape'}<CassetteTape size={24} />{/if}
                            {#if type === 'hdd'}<HardDrive size={24} />{/if}
                            {#if type === 'cloud'}<Cloud size={24} />{/if}
                            <span class="text-[10px] font-black uppercase tracking-widest">{type}</span>
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
                        </div>
                    </div>

                    {#if newMedia.media_type !== 'cloud'}
                        <div class="space-y-2 animate-in fade-in duration-300">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="location">Physical Location</label>
                            <div class="relative">
                                <MapPin size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                                <Input id="location" bind:value={newMedia.location} placeholder="Cabinet A, Shelf 2" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                            </div>
                        </div>
                    {/if}

                    <!-- Type Specific Fields -->
                    {#if newMedia.media_type === 'tape'}
                        <div class="space-y-6 animate-in slide-in-from-top-2">
                            <div class="grid grid-cols-1">
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="tier">Generation (LTO-6...)</label>
                                    <Input id="tier" bind:value={newMedia.generation_tier} class="h-12 bg-bg-primary/50 border-border-color" />
                                </div>
                            </div>

                            <div class="p-5 bg-bg-tertiary/50 border border-border-color rounded-xl space-y-4">
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center gap-2">
                                        <ShieldCheck size={18} class="text-blue-400" />
                                        <div class="flex flex-col">
                                            <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">Hardware LTO Encryption</span>
                                            <span class="text-[9px] text-text-secondary font-medium uppercase tracking-tighter opacity-50 italic">FIPS 140-2 Level 4 COMPLIANT</span>
                                        </div>
                                    </div>
                                    <input type="checkbox" bind:checked={newMedia.enable_encryption} class="w-5 h-5 rounded-md border-border-color bg-bg-primary text-blue-500 focus:ring-blue-500/20" />
                                </div>

                                {#if newMedia.enable_encryption}
                                    <div class="space-y-2 pt-2 animate-in fade-in slide-in-from-top-2 duration-300">
                                        <label for="enc_key" class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1">256-bit HEX Encryption Key (32 Bytes)</label>
                                        <Input
                                            id="enc_key"
                                            type="password"
                                            bind:value={newMedia.encryption_key}
                                            placeholder="00112233445566778899aabbccddeeff..."
                                            class="h-11 bg-bg-primary/80 border-blue-500/30 font-mono text-xs focus:border-blue-500/60"
                                        />
                                        <p class="text-[9px] text-text-secondary leading-relaxed opacity-60">WARNING: If you lose this key, the data on this tape is permanently unrecoverable. TapeHoard does not store keys in plain-text.</p>
                                    </div>
                                {/if}
                            </div>
                        </div>
                    {:else if newMedia.media_type === 'hdd'}
                        <div class="grid grid-cols-2 gap-6 animate-in slide-in-from-top-2">
                            <div class="space-y-2">
                                <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="mount">System Mount Point</label>
                                <Input id="mount" bind:value={newMedia.mount_path} placeholder="/mnt/backup" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="tier">Drive Tier (SATA...)</label>
                                <Input id="tier" bind:value={newMedia.generation_tier} class="h-12 bg-bg-primary/50 border-border-color" />
                            </div>
                        </div>
                    {:else if newMedia.media_type === 'cloud'}
                        <div class="space-y-6 animate-in slide-in-from-top-2">
                            <div class="space-y-2">
                                <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="bucket">Bucket Name</label>
                                <Input id="bucket" bind:value={newMedia.bucket_name} placeholder="my-backups" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>

                            <div class="p-5 bg-bg-tertiary/50 border border-border-color rounded-xl space-y-4">
                                <div class="flex items-center gap-2 mb-2">
                                    <ShieldCheck size={18} class="text-blue-400" />
                                    <div class="flex flex-col">
                                        <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">Cloud Security Bundle</span>
                                        <span class="text-[9px] text-text-secondary font-medium uppercase tracking-tighter opacity-50 italic">AES-256 Client-Side Encryption</span>
                                    </div>
                                </div>

                                <div class="grid grid-cols-2 gap-4">
                                    <div class="space-y-2">
                                        <label for="acc_key" class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1">Access Key</label>
                                        <Input id="acc_key" type="password" bind:value={newMedia.access_key} class="h-10 bg-bg-primary/80 border-border-color/50 font-mono text-xs" />
                                    </div>
                                    <div class="space-y-2">
                                        <label for="sec_key" class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1">Secret Key</label>
                                        <Input id="sec_key" type="password" bind:value={newMedia.secret_key} class="h-10 bg-bg-primary/80 border-border-color/50 font-mono text-xs" />
                                    </div>
                                </div>

                                <div class="space-y-2 pt-2 border-t border-border-color/30">
                                    <label for="cloud_pass" class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1">Local Encryption Passphrase</label>
                                    <Input id="cloud_pass" type="password" bind:value={newMedia.encryption_passphrase} placeholder="Keep this safe!" class="h-10 bg-bg-primary/80 border-blue-500/30 font-mono text-xs focus:border-blue-500/60" />
                                </div>
                            </div>

                            <!-- Advanced Hardware Toggle -->
                            <div class="pt-2">
                                <button
                                    type="button"
                                    class="text-[10px] font-black uppercase tracking-widest text-text-secondary hover:text-text-primary flex items-center gap-2 transition-colors"
                                    onclick={() => showAdvancedCloud = !showAdvancedCloud}
                                >
                                    <Monitor size={12} />
                                    {showAdvancedCloud ? 'Hide' : 'Show'} Advanced Provider Config
                                </button>

                                {#if showAdvancedCloud}
                                    <div class="grid grid-cols-2 gap-6 mt-4 p-5 bg-bg-primary/30 border border-border-color/40 rounded-xl animate-in slide-in-from-top-2 duration-300">
                                        <div class="space-y-2">
                                            <label class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1" for="endpoint">Endpoint URL</label>
                                            <Input id="endpoint" bind:value={newMedia.endpoint_url} placeholder="https://s3.amazonaws.com" class="h-10 bg-bg-primary/50 border-border-color font-mono text-xs" />
                                        </div>
                                        <div class="space-y-2">
                                            <label class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1" for="region">Region</label>
                                            <Input id="region" bind:value={newMedia.cloud_region} placeholder="us-east-1" class="h-10 bg-bg-primary/50 border-border-color font-mono text-xs" />
                                        </div>
                                        <div class="space-y-2 col-span-2">
                                            <label class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1" for="provider">Provider Label</label>
                                            <Input id="provider" bind:value={newMedia.cloud_provider} placeholder="AWS S3" class="h-10 bg-bg-primary/50 border-border-color font-mono text-xs" />
                                        </div>
                                    </div>
                                {/if}
                            </div>
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
                            {#if editingMedia.media_type === 'tape'}<CassetteTape size={20} />{/if}
                            {#if editingMedia.media_type === 'hdd'}<HardDrive size={20} />{/if}
                            {#if editingMedia.media_type === 'cloud'}<Cloud size={20} />{/if}
                        </div>
                        <div>
                            <span class="text-xs font-black text-text-primary uppercase tracking-widest">{editingMedia.identifier}</span>
                            <span class="text-[10px] text-text-secondary block opacity-60 uppercase">{editingMedia.media_type} &bull; {editingMedia.generation_tier}</span>
                        </div>
                    </div>

                    {#if editingMedia.media_type !== 'cloud'}
                        <div class="space-y-2 animate-in fade-in duration-300">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-location">Physical Location</label>
                            <Input id="edit-location" bind:value={editingMedia.location} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                        </div>
                    {/if}

                    {#if editingMedia.media_type === 'tape'}
                        <div class="space-y-2 opacity-50">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-hardware">LTO Hardware</label>
                            <div id="edit-hardware" class="h-12 bg-bg-primary/30 border border-border-color rounded-xl px-4 flex items-center text-xs font-mono text-text-secondary italic">
                                Using globally configured drive(s)
                            </div>
                        </div>
                    {:else if editingMedia.media_type === 'hdd'}
                        <div class="space-y-2">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-mount">System Mount Point</label>
                            <Input id="edit-mount" bind:value={editingMedia.config.mount_path} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                        </div>
                    {:else if editingMedia.media_type === 'cloud'}
                         <div class="space-y-2">
                            <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="edit-endpoint">Endpoint URL</label>
                            <Input id="edit-endpoint" bind:value={editingMedia.config.endpoint_url} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
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
