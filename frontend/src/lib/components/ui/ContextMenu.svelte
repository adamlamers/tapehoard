<script lang="ts">
    import { onMount, type Snippet } from 'svelte';
    import { fade } from 'svelte/transition';

    let {
        x = 0,
        y = 0,
        show = $bindable(false),
        children
    } = $props<{
        x: number;
        y: number;
        show: boolean;
        children: Snippet;
    }>();

    let menuElement = $state<HTMLElement | null>(null);

    // Adjust position to stay within viewport
    let adjustedX = $state(0);
    let adjustedY = $state(0);

    $effect(() => {
        if (show && menuElement) {
            const rect = menuElement.getBoundingClientRect();
            const padding = 10;

            let finalX = x;
            let finalY = y;

            if (x + rect.width > window.innerWidth - padding) {
                finalX = window.innerWidth - rect.width - padding;
            }
            if (y + rect.height > window.innerHeight - padding) {
                finalY = window.innerHeight - rect.height - padding;
            }

            adjustedX = finalX;
            adjustedY = finalY;
        }
    });

    function handleGlobalClick(e: MouseEvent) {
        if (show && menuElement && !menuElement.contains(e.target as Node)) {
            show = false;
        }
    }

    onMount(() => {
        window.addEventListener('click', handleGlobalClick, true);
        window.addEventListener('contextmenu', handleGlobalClick, true);
        return () => {
            window.removeEventListener('click', handleGlobalClick, true);
            window.removeEventListener('contextmenu', handleGlobalClick, true);
        };
    });
</script>

{#if show}
    <div
        bind:this={menuElement}
        transition:fade={{ duration: 100 }}
        class="fixed z-[100] min-w-[180px] bg-bg-secondary border border-border-color shadow-2xl rounded-xl p-1.5 backdrop-blur-xl"
        style="left: {adjustedX}px; top: {adjustedY}px;"
    >
        {@render children()}
    </div>
{/if}
