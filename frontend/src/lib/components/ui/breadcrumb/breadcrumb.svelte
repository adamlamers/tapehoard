<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLElement> = $props();
</script>

<nav aria-label="breadcrumb" class={cn("", className)} {...rest}>
	{@render children?.()}
</nav>
