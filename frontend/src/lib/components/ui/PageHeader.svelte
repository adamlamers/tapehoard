<script lang="ts">
    import { type Component, type Snippet } from 'svelte';
    import { cn } from '$lib/utils';

    interface Props {
        title: string;
        description?: string;
        icon?: any;
        actions?: Snippet;
        class?: string;
    }

    let { title, description, icon: Icon, actions, class: className }: Props = $props();
</script>

<header class={cn("flex justify-between items-center bg-bg-secondary px-6 py-4 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0", className)}>
    <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
    <div class="relative z-10">
        <h1 class="text-lg font-bold text-text-primary flex items-center gap-3">
            {#if Icon}
                <Icon class="text-blue-500" size={20} />
            {/if}
            {title}
        </h1>
        {#if description}
            <p class="text-sm text-text-secondary mt-1 opacity-70">
                {description}
            </p>
        {/if}
    </div>

    {#if actions}
        <div class="flex items-center gap-2 z-10">
            {@render actions()}
        </div>
    {/if}
</header>
