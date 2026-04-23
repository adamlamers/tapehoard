<script lang="ts">
    import { Search, Save, ShieldAlert } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';

    let globalExclusions = $state("*.tmp\nnode_modules/\n.DS_Store\nThumbs.db\nCache/\n");
</script>

<svelte:head>
    <title>Settings - TapeHoard</title>
</svelte:head>

<div class="flex justify-between items-center mb-8 bg-bg-secondary p-6 rounded-lg border border-border-color shadow-lg">
    <div>
        <h1 class="text-3xl font-bold tracking-tight text-text-primary">System Settings</h1>
        <p class="text-text-secondary mt-1">Configure global backup behavior and exclusion engines.</p>
    </div>
    <Button variant="default" size="lg" class="px-8 h-12">
        <Save size={20} class="mr-2" />
        Apply Settings
    </Button>
</div>

<div class="max-w-4xl mx-auto space-y-6">
    <Card class="p-8 shadow-xl border-border-color/60">
        <div class="flex items-center justify-between mb-6">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-action-color/10 rounded-lg">
                    <Search size={24} class="text-action-color" />
                </div>
                <div>
                    <h3 class="text-lg font-bold text-text-primary uppercase tracking-tight">Global Exclusion Engine</h3>
                    <p class="text-[12px] text-text-secondary font-medium">Define patterns that will be ignored across all backup sources.</p>
                </div>
            </div>
            <span class="text-[10px] font-mono text-text-secondary bg-bg-primary px-3 py-1 rounded-full border border-border-color">.gitignore syntax</span>
        </div>

        <div class="relative group">
            <textarea
                bind:value={globalExclusions}
                class="w-full h-[400px] bg-bg-primary/50 border border-border-color rounded-lg p-6 text-[14px] mono text-text-primary focus:ring-1 focus:ring-action-color focus:border-action-color focus:outline-none resize-none leading-relaxed transition-all"
                placeholder="e.g. *.tmp"
            ></textarea>
        </div>

        <div class="mt-6 p-4 bg-orange-500/5 border border-dashed border-orange-500/30 rounded-lg flex gap-4 items-start">
            <ShieldAlert size={20} class="text-orange-500 shrink-0 mt-0.5" />
            <p class="text-[12px] text-text-secondary leading-normal font-medium">
                <strong>WARNING:</strong> Broad exclusion patterns (like <code>*</code> or <code>/</code>) can lead to empty backups. Patterns are evaluated recursively. Use <code>!</code> to explicitly include a sub-pattern within an excluded directory.
            </p>
        </div>
    </Card>
</div>
