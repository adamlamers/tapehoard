<script lang="ts">
    import { Button } from './button';
    import { cn } from '$lib/utils';

    interface Props {
        icon: any;
        iconSize?: number;
        onclick?: (e: MouseEvent) => void;
        variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
        size?: 'sm' | 'md' | 'lg';
        class?: string;
        title?: string;
        disabled?: boolean;
        href?: string;
    }

    let {
        icon: Icon,
        iconSize,
        onclick,
        variant = 'ghost',
        size = 'md',
        class: className,
        title,
        disabled = false,
        href
    }: Props = $props();

    const sizes = {
        sm: { btn: 'h-7 w-7', icon: 12 },
        md: { btn: 'h-9 w-9', icon: 16 },
        lg: { btn: 'h-11 w-11', icon: 20 }
    };

    const currentSize = $derived(sizes[size]);
    const currentIconSize = $derived(iconSize || currentSize.icon);
</script>

<Button
    size="icon"
    {variant}
    {onclick}
    {href}
    class={cn(currentSize.btn, className)}
    {title}
    {disabled}
>
    <Icon size={currentIconSize} />
</Button>
