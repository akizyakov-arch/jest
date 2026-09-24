# SVG HUD / Tech Rune — Developer Logic Specification

**Версия:** 1.0  
**Связанный файл:** `tech_rune_neon_animated.svg`

---

# 1. Назначение

SVG используется как визуальный HUD-элемент поверх gesture-control интерфейса.

Важно:

- SVG **не участвует** в распознавании жестов;
- SVG получает только готовые состояния от Gesture / Interaction Engine;
- визуальный слой не должен напрямую управлять ОС;
- все состояния должны включаться и выключаться программно через CSS-классы или эквивалентный API.

Архитектура:

```text
Camera
  ↓
Hand Tracking
  ↓
Gesture Engine
  ↓
Interaction State
  ↓
Visual State Mapper
  ↓
SVG HUD
```

---

# 2. Базовый принцип

Gesture Engine не должен знать, как именно выглядит руна.

Он должен передавать только абстрактное состояние.

Пример:

```text
Gesture Engine:
PINCH_CONFIRMED

↓

Visual State Mapper:
CLICK

↓

SVG:
add class "is-click"
```

---

# 3. Основные состояния SVG

Поддерживаются следующие базовые классы:

```text
is-active
is-click
is-drag
is-paused
```

Дополнительно рекомендуется добавить:

```text
is-hover
is-scroll
is-context
is-swipe
is-error
is-disabled
```

---

# 4. Состояние DEFAULT

Когда система запущена, но не активна:

```text
state = STANDBY
```

Поведение:

- медленное вращение внешнего кольца;
- медленное вращение среднего кольца;
- лёгкое дыхание центральной руны;
- низкая яркость;
- orbit-dot двигается;
- нет ripple;
- нет активных snap-индикаторов.

Визуальная цель:

система жива, но не управляет компьютером.

---

# 5. is-active

Включается, когда gesture control находится в режиме `ACTIVE`.

Пример:

```javascript
svg.classList.add("is-active");
```

Поведение:

- ускоряется вращение колец;
- центральная руна становится ярче;
- повышается интенсивность glow;
- возможно усиление orbit-dot;
- визуально должно быть понятно, что управление включено.

Событие включения:

```text
OPEN_PALM_HOLD_CONFIRMED
```

Событие выключения:

```text
OPEN_PALM_HOLD_CONFIRMED
while ACTIVE
```

или:

```text
SYSTEM_PAUSE
```

---

# 6. is-click

Кратковременное состояние.

Событие:

```text
PINCH_CLICK
```

Поведение:

- запускается ripple-анимация;
- центральная руна может кратко вспыхнуть;
- длительность 250–450 мс;
- состояние автоматически снимается после окончания анимации.

Пример:

```javascript
function playClickFx(svg) {
    svg.classList.remove("is-click");
    void svg.offsetWidth; // restart CSS animation
    svg.classList.add("is-click");

    setTimeout(() => {
        svg.classList.remove("is-click");
    }, 450);
}
```

---

# 7. is-drag

Включается при захвате объекта.

Событие начала:

```text
DRAG_START
```

Событие окончания:

```text
DRAG_END
```

Поведение:

- кольца вращаются быстрее;
- центральная руна немного увеличивается;
- glow становится ярче;
- может появляться лёгкий motion trail;
- эффект должен продолжаться всё время drag.

Пример:

```javascript
svg.classList.add("is-drag");
```

При окончании:

```javascript
svg.classList.remove("is-drag");
```

---

# 8. is-paused

Используется для:

```text
PAUSED
STANDBY
TRACKING_LOST
```

Поведение:

- анимация останавливается или сильно замедляется;
- opacity уменьшается;
- руна остаётся видимой;
- не должно быть активных ripple / drag эффектов.

Пример:

```javascript
svg.classList.add("is-paused");
```

---

# 9. Рекомендуемое расширение состояний

## is-hover

Когда рука отслеживается и pointer активен.

```text
POINTER_ACTIVE
```

Поведение:

- лёгкое повышение яркости;
- внутреннее кольцо может реагировать на движение;
- центральная руна остаётся спокойной.

---

## is-scroll

Когда Gesture Engine распознал scroll mode.

```text
SCROLL_START
SCROLL_UPDATE
SCROLL_END
```

Поведение:

- внутреннее кольцо вращается в направлении scroll;
- вертикальная шкала / дуга может визуально смещаться;
- скорость анимации пропорциональна скорости scroll.

Пример:

```javascript
svg.style.setProperty("--scroll-speed", normalizedSpeed);
```

---

## is-context

Событие:

```text
CONTEXT_ACTION
```

Поведение:

- кольцо вокруг центральной руны сжимается;
- короткая пауза;
- затем раскрывается;
- цвет остаётся синим.

---

## is-swipe

Событие:

```text
SWIPE_LEFT
SWIPE_RIGHT
SWIPE_UP
SWIPE_DOWN
```

Поведение:

- внешний сегмент кольца смещается в направлении swipe;
- допускается вращение по направлению движения;
- короткий burst на 200–350 мс.

---

## is-error

Используется только для технической ошибки:

```text
CAMERA_ERROR
TRACKING_ERROR
INPUT_ERROR
```

Поведение:

- анимация останавливается;
- glow уменьшается;
- допустимо мигание 1–2 раза;
- не использовать агрессивную красную стилизацию, если дизайн должен оставаться единым.

---

# 10. Таблица Gesture → Visual State

| Gesture / Event | Visual State |
|---|---|
| STANDBY | default / is-paused |
| ACTIVE | is-active |
| POINTER_ACTIVE | is-hover |
| PINCH_CLICK | is-click |
| DRAG_START | is-drag |
| DRAG_END | remove is-drag |
| SCROLL_START | is-scroll |
| SCROLL_END | remove is-scroll |
| CONTEXT_ACTION | is-context |
| SWIPE_* | is-swipe |
| TRACKING_LOST | is-paused |
| SYSTEM_DISABLE | is-disabled |

---

# 11. Visual State Manager

Рекомендуется создать отдельный модуль:

```text
visual_state_manager
```

Он получает события:

```text
GestureEvent
InteractionEvent
SystemEvent
```

И преобразует их в состояние визуализации.

Пример структуры:

```python
class VisualStateManager:
    def on_event(self, event):
        if event.type == "PINCH_CLICK":
            return "CLICK"

        if event.type == "DRAG_START":
            return "DRAG"

        if event.type == "DRAG_END":
            return "ACTIVE"

        if event.type == "SCROLL_START":
            return "SCROLL"
```

---

# 12. Не смешивать persistent и transient states

Есть два типа состояний.

## Persistent

Действуют долго:

```text
ACTIVE
PAUSED
DRAG
SCROLL
```

## Transient

Короткая вспышка:

```text
CLICK
CONTEXT
SWIPE
ERROR_PULSE
```

Transient state не должен уничтожать persistent state.

Пример:

```text
ACTIVE
  +
CLICK
```

После click система должна вернуться в `ACTIVE`, а не в default.

---

# 13. Рекомендуемая модель состояния

Использовать два слоя:

```text
BaseState
EffectState
```

Пример:

```text
BaseState = ACTIVE
EffectState = CLICK
```

После завершения эффекта:

```text
BaseState = ACTIVE
EffectState = NONE
```

---

# 14. Скорость вращения

Скорость вращения можно использовать как индикатор активности.

Пример:

```text
STANDBY → 12 s / revolution
ACTIVE  → 6 s
DRAG    → 2.8 s
SCROLL  → dynamic
```

Не делать слишком высокую скорость.

Главная задача — ощущение реакции, а не постоянное мельтешение.

---

# 15. Направление вращения

Рекомендуется:

```text
outer ring  → clockwise
middle ring → counter-clockwise
inner ring  → clockwise
```

Это создаёт глубину без сложной графики.

---

# 16. Реакция на движение руки

Дополнительно можно передавать в HUD:

```text
handVelocityX
handVelocityY
handSpeed
```

Пример:

```javascript
const speed = Math.min(1, handSpeed);

svg.style.setProperty("--motion-intensity", speed);
```

Можно использовать для:

- ускорения вращения;
- яркости;
- trail;
- деформации дуг;
- смещения orbit-dot.

---

# 17. Реакция на положение руки

HUD может быть привязан:

- к центру ладони;
- к активному пальцу;
- к экранному курсору.

Для основного HUD рекомендуется:

```text
position = palm center
```

Для click ripple:

```text
position = index finger / pinch point
```

---

# 18. Размер HUD

Размер должен масштабироваться от размера кисти.

Пример:

```text
HUD radius ≈ 1.3–1.8 × palm width
```

Ограничения:

```text
minSize
maxSize
```

нужно задавать в UI-конфигурации.

---

# 19. Сглаживание движения HUD

HUD не должен дрожать вместе с raw landmarks.

Использовать отдельный smoothing.

Рекомендуется:

```text
EMA
или
One Euro Filter
```

Важно:

HUD smoothing может быть сильнее, чем cursor smoothing.

---

# 20. Ориентация HUD

По умолчанию HUD остаётся ориентированным по экрану.

Не нужно полностью вращать весь SVG вслед за кистью.

Допустимо:

- слегка поворачивать внутреннюю руну;
- максимум ±10–15°;
- только для визуального эффекта.

---

# 21. Visual FX Modes

Поддерживать три режима:

```text
FULL
MINIMAL
OFF
```

## FULL

- все кольца;
- руна;
- orbit-dot;
- motion effects;
- ripple;
- labels;
- snap zones.

## MINIMAL

- центральная руна;
- одно кольцо;
- click ripple;
- active / paused state.

## OFF

- SVG полностью скрыт;
- gesture engine продолжает работать.

---

# 22. Производительность

SVG не должен снижать FPS gesture tracking.

Рекомендуется:

- CSS transform;
- opacity;
- stroke-dashoffset;
- минимум DOM-элементов;
- избегать тяжёлых blur-фильтров на слабых GPU;
- иметь low-performance mode.

---

# 23. Low Performance Mode

Добавить настройку:

```text
Visual Quality:
HIGH
MEDIUM
LOW
```

LOW:

- отключить blur;
- отключить motion trail;
- уменьшить количество glow;
- оставить только линии и transform.

---

# 24. Запрещённые архитектурные решения

Нельзя:

```text
SVG onclick → Windows click
```

Нельзя:

```text
CSS animation event → gesture logic
```

Нельзя:

```text
Visual state → input command
```

Разрешено только:

```text
Gesture / Interaction Engine
        ↓
Visual State Manager
        ↓
SVG
```

---

# 25. Пример JS API

Рекомендуемый внешний интерфейс:

```javascript
hud.setBaseState("active");
hud.triggerEffect("click");

hud.setPosition(x, y);
hud.setScale(scale);

hud.setMotion({
    vx: 0.25,
    vy: -0.12,
    speed: 0.43
});

hud.setMode("full");
```

---

# 26. Пример реализации

```javascript
class RuneHUD {
    constructor(svg) {
        this.svg = svg;
        this.baseState = "standby";
    }

    setBaseState(state) {
        this.svg.classList.remove(
            "is-active",
            "is-drag",
            "is-paused",
            "is-scroll"
        );

        this.baseState = state;

        if (state === "active") {
            this.svg.classList.add("is-active");
        }

        if (state === "drag") {
            this.svg.classList.add("is-active", "is-drag");
        }

        if (state === "paused") {
            this.svg.classList.add("is-paused");
        }

        if (state === "scroll") {
            this.svg.classList.add("is-active", "is-scroll");
        }
    }

    triggerEffect(effect) {
        if (effect === "click") {
            this.svg.classList.remove("is-click");
            void this.svg.offsetWidth;
            this.svg.classList.add("is-click");

            setTimeout(() => {
                this.svg.classList.remove("is-click");
            }, 450);
        }
    }
}
```

---

# 27. Первый MVP для HUD

В первой версии достаточно:

```text
DEFAULT
ACTIVE
CLICK
DRAG
PAUSED
```

Не добавлять сразу все visual states.

После стабилизации добавить:

```text
SCROLL
SWIPE
CONTEXT
SNAP
ERROR
```

---

# 28. Итоговая логика

```text
STANDBY
   ↓ open palm hold
ACTIVE
   ↓ pinch
CLICK FX
   ↓
ACTIVE
   ↓ pinch + move
DRAG
   ↓ release
ACTIVE
   ↓ tracking lost
PAUSED
```

Главный принцип:

> SVG — это визуальная реакция на состояние системы, а не источник управления.
