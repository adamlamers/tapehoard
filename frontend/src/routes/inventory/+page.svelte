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
        Star
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
        getSettingsSystemSettingsGet,
        updateSettingSystemSettingsPost,
        type MediaSchema
    } from '$lib/api';
    import { toast } from 'svelte-sonner';

    let mediaList = $state<MediaSchema[]>([]);
    let loading = $state(true);
    let showRegisterDialog = $state(false);
    let primaryTargetId = $state<string | null>(null);

    // New Media Form State
    let newMedia = $state({
        media_type: 'tape',
        identifier: '',
        generation_tier: 'LTO-6',
        capacity_gb: 2500,
        location: 'Storage Shelf',
        // Type-specific config
        device_path: '/dev/nst0', // For Tape
        encryption_key: '', // 256-bit Hex Key
        enable_encryption: false,
        mount_path: '', // For HDD
        bucket_name: '', // For Cloud
        cloud_provider: 'AWS S3',
        cloud_region: 'us-east-1',
        endpoint_url: '' // For Custom S3
    });

    async function loadMedia() {
        loading = true;
        try {
            const [mediaRes, settingsRes] = await Promise.all([
                listMediaInventoryMediaGet(),
                getSettingsSystemSettingsGet()
            ]);

            if (mediaRes.data) {
                mediaList = mediaRes.data;
            }
            if (settingsRes.data?.primary_archival_target) {
                primaryTargetId = settingsRes.data.primary_archival_target;
            }
        } catch (error) {
            toast.error("Failed to load media fleet");
        } finally {
            loading = false;
        }
    }

    async function setPrimaryTarget(mediaId: number) {
        try {
            const idStr = mediaId.toString();
            await updateSettingSystemSettingsPost({
                body: { key: "primary_archival_target", value: idStr }
            });
            primaryTargetId = idStr;
            toast.success("Primary archival target updated");
        } catch (error) {
            toast.error("Failed to set primary target");
        }
    }

    async function handleInitialize(mediaId: number, identifier: string) {
        if (!confirm(`Are you sure you want to initialize ${identifier}? This may wipe existing data on the media.`)) return;

        try {
            toast.info(`Initializing ${identifier}...`);
            await initializeMediaInventoryMediaMediaIdInitializePost({
                path: { media_id: mediaId }
            });
            toast.success(`${identifier} initialized successfully`);
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to initialize media");
        }
    }

    async function handleStartBackup(mediaId: number, identifier: string) {        try {
            await triggerBackupBackupsTriggerMediaIdPost({
                path: { media_id: mediaId }
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
            config.device_path = newMedia.device_path;
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
                }
            });
            toast.success(`${newMedia.identifier} registered in fleet`);
            showRegisterDialog = false;
            loadMedia();
        } catch (error) {
            toast.error("Failed to register media");
        }
    }

    async function handleDelete(mediaId: number) {
        if (!confirm("Are you sure? This will remove the media from the system index.")) return;
        try {
            await deleteMediaInventoryMediaMediaIdDelete({
                path: { media_id: mediaId }
            });
            toast.success("Media removed from fleet");
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
    <title>Media Fleet - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 h-full overflow-hidden animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <CassetteTape class="text-blue-500" size={28} />
                Media Fleet
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Physical Asset Management & Archival Targets
            </p>
        </div>

        <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px] z-10" onclick={() => showRegisterDialog = true}>
            <Plus size={18} class="mr-2" /> Register New Media
        </Button>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto pr-2 pb-12">
        <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden">
            <table class="w-full border-collapse">
                <thead>
                    <tr class="bg-bg-tertiary/50 border-b border-border-color">
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Primary</th>
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Identity</th>
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Type & Tier</th>
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Location</th>
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Utilization</th>
                        <th class="px-6 py-4 text-left text-[10px] font-black uppercase tracking-widest text-text-secondary">Status</th>
                        <th class="px-6 py-4 text-right text-[10px] font-black uppercase tracking-widest text-text-secondary">Actions</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-border-color/30">
                    {#each mediaList as media (media.id)}
                        <tr class="hover:bg-bg-primary/30 transition-colors group">
                            <td class="px-6 py-4">
                                <button
                                    class={cn(
                                        "p-2 rounded-lg border transition-all",
                                        primaryTargetId === media.id.toString()
                                            ? "bg-yellow-500/10 border-yellow-500/50 text-yellow-500 shadow-[0_0_10px_rgba(234,179,8,0.2)]"
                                            : "bg-bg-primary border-border-color text-text-secondary opacity-20 hover:opacity-100 hover:border-yellow-500/30"
                                    )}
                                    onclick={() => setPrimaryTarget(media.id)}
                                    title="Set as primary archival target"
                                >
                                    <Star size={16} fill={primaryTargetId === media.id.toString() ? "currentColor" : "none"} />
                                </button>
                            </td>
                            <td class="px-6 py-4">
                                <div class="flex items-center gap-3">
                                    <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500">
                                        {#if media.media_type === 'tape'}<CassetteTape size={18} />{/if}
                                        {#if media.media_type === 'hdd'}<HardDrive size={18} />{/if}
                                        {#if media.media_type === 'cloud'}<Cloud size={18} />{/if}
                                    </div>
                                    <div>
                                        <span class="text-sm font-black text-text-primary mono tracking-tight">{media.identifier}</span>
                                        <div class="flex gap-2 mt-0.5">
                                            {#if media.config?.encryption_key}
                                                <span class="text-[8px] font-black uppercase tracking-tighter text-blue-400 bg-blue-500/10 px-1 rounded flex items-center gap-1">
                                                    <ShieldCheck size={8} /> ENCRYPTED
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
                            <td class="px-6 py-4">
                                <span class={cn("px-2.5 py-1 rounded text-[9px] font-black uppercase tracking-widest border",
                                    media.status === 'active' ? "bg-success-color/10 text-success-color border-success-color/20" : "bg-bg-primary text-text-secondary border-border-color"
                                )}>
                                    {media.status}
                                </span>
                            </td>
                            <td class="px-6 py-4 text-right">
                                <div class="flex items-center justify-end gap-2">
                                    {#if media.status === 'active'}
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            class="h-9 px-4 font-black uppercase tracking-widest text-[9px] border-action-color/30 text-action-color hover:bg-action-color/10"
                                            onclick={() => handleInitialize(media.id, media.identifier)}
                                        >
                                            <RotateCw size={14} class="mr-1.5" /> Initialize
                                        </Button>
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            class="h-9 px-4 font-black uppercase tracking-widest text-[9px] border-success-color/30 text-success-color hover:bg-success-color/10"
                                            onclick={() => handleStartBackup(media.id, media.identifier)}
                                        >
                                            <PlayCircle size={14} class="mr-1.5" /> Initiate Archival
                                        </Button>
                                    {/if}
                                    <Button variant="ghost" size="icon" class="h-9 w-9 hover:bg-error-color/10 hover:text-error-color" onclick={() => handleDelete(media.id)}><Trash2 size={16} /></Button>
                                </div>
                            </td>
                        </tr>
                    {:else}
                        <tr><td colspan="7" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-black uppercase tracking-[0.2em]">No Media Assets Registered</p></td></tr>
                    {/each}
                </tbody>
            </table>
        </Card>
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

                    <div class="space-y-2">
                        <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="location">Physical Location</label>
                        <div class="relative">
                            <MapPin size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                            <Input id="location" bind:value={newMedia.location} placeholder="Cabinet A, Shelf 2" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                        </div>
                    </div>

                    <!-- Type Specific Fields -->
                    {#if newMedia.media_type === 'tape'}
                        <div class="space-y-6 animate-in slide-in-from-top-2">
                            <div class="grid grid-cols-2 gap-6">
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="device">Tape Device Path</label>
                                    <Input id="device" bind:value={newMedia.device_path} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
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
                        <div class="space-y-4 animate-in slide-in-from-top-2">
                            <div class="grid grid-cols-2 gap-6">
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="bucket">Bucket Name</label>
                                    <Input id="bucket" bind:value={newMedia.bucket_name} placeholder="my-backups" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="provider">Provider (S3/B2...)</label>
                                    <Input id="provider" bind:value={newMedia.cloud_provider} class="h-12 bg-bg-primary/50 border-border-color" />
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-6">
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="region">Region</label>
                                    <Input id="region" bind:value={newMedia.cloud_region} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                                <div class="space-y-2">
                                    <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="endpoint">Endpoint URL (Optional)</label>
                                    <Input id="endpoint" bind:value={newMedia.endpoint_url} placeholder="https://s3.amazonaws.com" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
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
</div>
