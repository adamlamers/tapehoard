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
        PlayCircle
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
        type MediaSchema
    } from '$lib/api';
    import { toast } from 'svelte-sonner';

    let mediaList = $state<MediaSchema[]>([]);
    let loading = $state(true);
    let showRegisterDialog = $state(false);

    // New Media Form State
    let newMedia = $state({
        media_type: 'tape',
        identifier: '',
        generation_tier: 'LTO-6',
        capacity_gb: 2500,
        location: 'Storage Shelf',
        // Type-specific config
        device_path: '/dev/nst0', // For Tape
        mount_path: '', // For HDD
        bucket_name: '', // For Cloud
        cloud_provider: 'AWS S3',
        cloud_region: 'us-east-1',
        endpoint_url: '' // For Custom S3
    });

    async function loadMedia() {
        loading = true;
        try {
            const response = await listMediaInventoryMediaGet();
            if (response.data) {
                mediaList = response.data;
            }
        } catch (error) {
            toast.error("Failed to load media fleet");
        } finally {
            loading = false;
        }
    }

    async function handleStartBackup(mediaId: number, identifier: string) {
        try {
            await triggerBackupBackupsTriggerMediaIdPost({
                path: { media_id: mediaId }
            });
            toast.success(`Backup job initiated for ${identifier}`);
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start backup");
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
        } else if (newMedia.media_type === 'hdd') {
            if (!newMedia.mount_path) { toast.error("Mount path required"); return; }
            config.mount_path = newMedia.mount_path;
        } else if (newMedia.media_type === 'cloud') {
            if (!newMedia.bucket_name) { toast.error("Bucket name required"); return; }
            config.bucket_name = newMedia.bucket_name;
            config.provider = newMedia.cloud_provider;
            config.region = newMedia.cloud_region;
            if (newMedia.endpoint_url) config.endpoint_url = newMedia.endpoint_url;
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
            toast.success(`${newMedia.identifier} registered`);
            showRegisterDialog = false;
            loadMedia();
            newMedia.identifier = '';
            newMedia.mount_path = '';
        } catch (error: any) {
            toast.error(error.body?.detail || "Registration failed");
        }
    }

    async function handleDelete(mediaId: number) {
        if (!confirm("Remove this media?")) return;
        try {
            await deleteMediaInventoryMediaMediaIdDelete({
                path: { media_id: mediaId }
            });
            toast.success("Removed");
            loadMedia();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed");
        }
    }

    onMount(loadMedia);

    function getPercentage(used: number, capacity: number) {
        if (capacity === 0) return 0;
        return Math.min(100, Math.round((used / capacity) * 100));
    }

    function formatSize(bytes: number) {
        if (bytes === 0) return "0 GB";
        const gb = bytes / (1024 * 1024 * 1024);
        if (gb >= 1000) return `${(gb / 1024).toFixed(1)} TB`;
        return `${gb.toFixed(0)} GB`;
    }

    const totalCapacity = $derived(mediaList.reduce((acc, m) => acc + m.capacity, 0));
    const totalUsed = $derived(mediaList.reduce((acc, m) => acc + m.bytes_used, 0));
    const globalUtilization = $derived(totalCapacity > 0 ? Math.round((totalUsed / totalCapacity) * 100) : 0);
</script>

<svelte:head>
    <title>Physical Media - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 relative">
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <CassetteTape class="text-blue-500" size={28} />
                Physical Media
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">Inventory & Media Configuration</p>
        </div>
        <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px] z-10" onclick={() => showRegisterDialog = true}>
            <Plus size={18} class="mr-2" /> Register New Media
        </Button>
    </header>

    {#if loading && mediaList.length === 0}
         <div class="flex flex-col items-center justify-center py-24 gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-blue-500" />
            <span class="text-xs font-black uppercase tracking-widest">Auditing Fleet Status...</span>
        </div>
    {:else}
        <div class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500 flex-1">
            <!-- Stats -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
                <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color p-5 flex items-center gap-4 shadow-xl">
                    <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><CassetteTape size={24} /></div>
                    <div><span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Total Media</span><span class="text-2xl font-black text-text-primary mono tracking-tighter">{mediaList.length}</span></div>
                </Card>
                <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color p-5 flex items-center gap-4 shadow-xl">
                    <div class="p-3 bg-action-color/10 rounded-xl text-action-color border border-action-color/20"><Database size={24} /></div>
                    <div><span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Fleet Capacity</span><span class="text-2xl font-black text-text-primary mono tracking-tighter">{formatSize(totalCapacity)}</span></div>
                </Card>
                <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color p-5 flex items-center gap-4 shadow-xl">
                    <div class="p-3 bg-success-color/10 rounded-xl text-success-color border border-success-color/20"><ShieldCheck size={24} /></div>
                    <div><span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Active Usage</span><span class="text-2xl font-black text-text-primary mono tracking-tighter">{formatSize(totalUsed)}</span></div>
                </Card>
                <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color p-5 flex items-center gap-4 shadow-xl">
                    <div class="p-3 bg-orange-500/10 rounded-xl text-orange-500 border border-orange-500/20"><RotateCw size={24} /></div>
                    <div><span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Utilization</span><span class="text-2xl font-black text-text-primary mono tracking-tighter">{globalUtilization}%</span></div>
                </Card>
            </div>

            <!-- Table -->
            <Card class="overflow-hidden border-border-color bg-bg-secondary shadow-2xl">
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="bg-bg-tertiary/50 border-b border-border-color">
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary">Identifier</th>
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary">Spec / Tier</th>
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary">System Config</th>
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary">Usage</th>
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary">Lifecycle</th>
                                <th class="px-8 py-5 text-[10px] font-black uppercase tracking-widest text-text-secondary text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-border-color/40">
                            {#each mediaList as media (media.id)}
                                <tr class="hover:bg-white/[0.02] transition-colors group">
                                    <td class="px-8 py-5">
                                        <div class="flex flex-col">
                                            <span class="mono font-black text-text-primary text-sm">{media.identifier}</span>
                                            <span class="text-[9px] font-bold text-text-secondary/50 uppercase tracking-tighter">LOC: {media.location || 'Unknown'}</span>
                                        </div>
                                    </td>
                                    <td class="px-8 py-5">
                                        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-bg-primary text-text-primary text-[10px] font-black border border-border-color uppercase">
                                            {#if media.media_type === 'tape'}<CassetteTape size={12} class="text-blue-400" />{:else if media.media_type === 'hdd'}<HardDrive size={12} class="text-yellow-400" />{:else}<Cloud size={12} class="text-green-400" />{/if}
                                            {media.generation_tier || media.media_type}
                                        </span>
                                    </td>
                                    <td class="px-8 py-5">
                                        <div class="flex flex-col gap-1">
                                            {#if media.media_type === 'tape' && media.config.device_path}
                                                <div class="flex items-center gap-1.5 text-[10px] font-bold mono text-text-secondary"><Monitor size={10} class="opacity-50" /> {media.config.device_path}</div>
                                            {:else if media.media_type === 'hdd' && media.config.mount_path}
                                                <div class="flex items-center gap-1.5 text-[10px] font-bold mono text-text-secondary"><HardDrive size={10} class="opacity-50" /> {media.config.mount_path}</div>
                                            {:else if media.media_type === 'cloud' && media.config.bucket_name}
                                                <div class="flex items-center gap-1.5 text-[10px] font-bold mono text-text-secondary"><Globe size={10} class="opacity-50" /> {media.config.bucket_name}</div>
                                            {:else}
                                                <span class="text-[9px] font-bold uppercase tracking-tighter text-text-secondary opacity-30">No config</span>
                                            {/if}
                                        </div>
                                    </td>
                                    <td class="px-8 py-5">
                                        <div class="flex flex-col gap-2 w-40">
                                            <div class="w-full bg-bg-primary rounded-full h-1.5 overflow-hidden shadow-inner border border-white/5">
                                                <div class={cn("h-full transition-all", media.status === 'full' ? 'bg-error-color' : 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]')} style="width: {getPercentage(media.bytes_used, media.capacity)}%"></div>
                                            </div>
                                            <span class="mono text-[9px] font-bold text-text-secondary opacity-70">{formatSize(media.bytes_used)} / {formatSize(media.capacity)}</span>
                                        </div>
                                    </td>
                                    <td class="px-8 py-5">
                                        <div class="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-text-primary">
                                            <div class={cn("w-2.5 h-2.5 rounded-full", media.status === 'active' ? 'bg-success-color shadow-[0_0_10px_rgba(46,204,113,0.5)]' : 'bg-error-color')}></div>
                                            {media.status}
                                        </div>
                                    </td>
                                    <td class="px-8 py-5 text-right">
                                        <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-all">
                                            {#if media.status === 'active'}
                                                <Button
                                                    variant="secondary"
                                                    size="sm"
                                                    class="h-9 px-4 font-black uppercase tracking-widest text-[9px] border-blue-500/30 text-blue-400 hover:bg-blue-500/10"
                                                    onclick={() => handleStartBackup(media.id, media.identifier)}
                                                >
                                                    <PlayCircle size={14} class="mr-1.5" /> Start Backup
                                                </Button>
                                            {/if}
                                            <Button variant="ghost" size="icon" class="h-9 w-9 hover:bg-error-color/10 hover:text-error-color" onclick={() => handleDelete(media.id)}><Trash2 size={16} /></Button>
                                        </div>
                                    </td>
                                </tr>
                            {:else}
                                <tr><td colspan="6" class="px-8 py-24 text-center opacity-20"><Database size={48} class="mx-auto mb-3" /><p class="text-sm font-black uppercase tracking-[0.2em]">No Media Assets Registered</p></td></tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </Card>
        </div>
    {/if}
</div>

<!-- REGISTRATION DIALOG -->
{#if showRegisterDialog}
    <div class="fixed inset-0 z-[999] flex items-center justify-center p-4 overflow-y-auto bg-black/80 backdrop-blur-md">
        <div class="absolute inset-0 cursor-pointer" onclick={() => showRegisterDialog = false} role="none"></div>
        <Card class="relative z-[1000] w-[600px] bg-bg-secondary border-border-color shadow-[0_30px_150px_rgba(0,0,0,1)] overflow-hidden animate-in zoom-in-95 duration-300 my-auto">
            <div class="p-8 border-b border-border-color bg-bg-tertiary/30">
                <div class="flex justify-between items-center mb-2">
                    <h2 class="text-2xl font-black uppercase tracking-tighter text-text-primary">Register Media</h2>
                    <button class="text-text-secondary hover:text-text-primary" onclick={() => showRegisterDialog = false}><X size={24} /></button>
                </div>
                <p class="text-[11px] font-bold uppercase tracking-widest text-text-secondary opacity-60">Provision new physical storage unit</p>
            </div>

            <div class="p-8 space-y-8">
                <!-- Type Selection -->
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

                    <!-- Type Specific Fields -->
                    {#if newMedia.media_type === 'tape'}
                        <div class="grid grid-cols-2 gap-6 animate-in slide-in-from-top-2">
                            <div class="space-y-2">
                                <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="device">Tape Device Path</label>
                                <Input id="device" bind:value={newMedia.device_path} class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            </div>
                            <div class="space-y-2">
                                <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="tier">Generation (LTO-6...)</label>
                                <Input id="tier" bind:value={newMedia.generation_tier} class="h-12 bg-bg-primary/50 border-border-color" />
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
                                    <Input id="endpoint" bind:value={newMedia.endpoint_url} placeholder="https://s3.us-west-004..." class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                </div>
                            </div>
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <label class="text-[10px] font-black uppercase tracking-widest text-text-secondary ml-1" for="location">Physical Location</label>
                        <Input id="location" bind:value={newMedia.location} placeholder="e.g. Bank Vault" class="h-12 bg-bg-primary/50 border-border-color" />
                    </div>
                </div>
            </div>

            <div class="p-8 bg-bg-tertiary/30 border-t border-border-color flex gap-4">
                <Button variant="outline" class="flex-1 h-12 font-black uppercase tracking-widest text-[11px]" onclick={() => showRegisterDialog = false}>Cancel</Button>
                <Button variant="default" class="flex-1 h-12 font-black uppercase tracking-widest text-[11px] shadow-lg shadow-blue-500/20" onclick={handleRegister}>
                    <Save size={18} class="mr-2" /> Commit to Fleet
                </Button>
            </div>
        </Card>
    </div>
{/if}
