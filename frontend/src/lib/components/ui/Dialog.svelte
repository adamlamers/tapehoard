<script lang="ts">
    import { type Snippet } from 'svelte';
    import { fade } from 'svelte/transition';
    import { cn } from '$lib/utils';

    interface Props {
        show: boolean;
        onClose: () => void;
        children: Snippet;
        class?: string;
        ariaLabelledBy?: string;
    }

    let { show, onClose, children, class: className, ariaLabelledBy }: Props = $props();

    function handleMousedown(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            onClose();
        }
    }
</script>

{#if show}
    <div
        class="fixed inset-0 z-[1200] bg-black/90 backdrop-blur-md flex items-center justify-center p-6"
        onmousedown={handleMousedown}
        transition:fade={{ duration: 200 }}
        role="presentation"
    >
        <div
            class={cn("relative animate-in zoom-in-95 duration-300", className)}
            onmousedown={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby={ariaLabelledBy}
            tabindex="-1"
        >
            {@render children()}
        </div>
    </div>
{/if}
