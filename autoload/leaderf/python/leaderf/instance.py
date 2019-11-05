#!/usr/bin/env python
# -*- coding: utf-8 -*-

import vim
import re
import os
import os.path
import time
import itertools
from .utils import *


class PopupWindow(object):
    def __init__(self, winid, buffer, tabpage):
        self._winid = winid
        self._buffer = buffer
        self._tabpage = tabpage

    @property
    def id(self):
        return self._winid

    @property
    def buffer(self):
        return self._buffer

    @buffer.setter
    def buffer(self, buffer):
        self._buffer = buffer

    @property
    def tabpage(self):
        return self._tabpage

    @property
    def cursor(self):
        # the col of window.cursor starts from 0, while the col of getpos() starts from 1
        lfCmd("""call win_execute(%d, 'let cursor_pos = getpos(".")') | let cursor_pos[2] -= 1""" % self._winid)
        return [int(i) for i in lfEval("cursor_pos[1:2]")]

    @cursor.setter
    def cursor(self, cursor):
        cursor = [cursor[0], cursor[1]+1]
        lfCmd("""call win_execute(%d, 'call cursor(%s)')""" % (self._winid, str(cursor)))

    @property
    def height(self):
        return int(lfEval("winheight(%d)" % self._winid))

    @property
    def width(self):
        return int(lfEval("winwidth(%d)" % self._winid))

    @property
    def number(self):
        return int(lfEval("win_id2win(%d)" % self._winid))

    @property
    def valid(self):
        return int(lfEval("winbufnr(%d)" % self._winid)) != -1

    def close(self):
        lfCmd("call popup_close(%d)" % self._winid)

    def show(self):
        lfCmd("call popup_show(%d)" % self._winid)

    def hide(self):
        lfCmd("call popup_hide(%d)" % self._winid)


class LfPopupInstance(object):
    def __init__(self):
        self._popup_wins = {
                "content_win": None,
                "input_win": None,
                "statusline_win": None,
                }

    def close(self):
        for win in self._popup_wins.values():
            if win:
                win.close()

    def show(self):
        for win in self._popup_wins.values():
            if win:
                win.show()

    def hide(self):
        for win in self._popup_wins.values():
            if win:
                win.hide()

    @property
    def content_win(self):
        return self._popup_wins["content_win"]

    @content_win.setter
    def content_win(self, content_win):
        self._popup_wins["content_win"] = content_win

    @property
    def input_win(self):
        return self._popup_wins["input_win"]

    @input_win.setter
    def input_win(self, input_win):
        self._popup_wins["input_win"] = input_win

    @property
    def statusline_win(self):
        return self._popup_wins["statusline_win"]

    @statusline_win.setter
    def statusline_win(self, statusline_win):
        self._popup_wins["statusline_win"] = statusline_win

    def getWinIdList(self):
        return [win.id for win in self._popup_wins.values() if win is not None]

#*****************************************************
# LfInstance
#*****************************************************
class LfInstance(object):
    """
    This class is used to indicate the LeaderF instance, which including
    the tabpage, the window, the buffer, the statusline, etc.
    """
    def __init__(self, category, cli,
                 before_enter_cb,
                 after_enter_cb,
                 before_exit_cb,
                 after_exit_cb):
        self._category = category
        self._cli = cli
        self._cli.setInstance(self)
        self._before_enter = before_enter_cb
        self._after_enter = after_enter_cb
        self._before_exit = before_exit_cb
        self._after_exit = after_exit_cb
        self._tabpage_object = None
        self._window_object = None
        self._buffer_object = None
        self._buffer_name = lfEval("expand('$VIMRUNTIME/')") + category + '/LeaderF'
        self._win_height = float(lfEval("g:Lf_WindowHeight"))
        self._show_tabline = int(lfEval("&showtabline"))
        self._is_autocmd_set = False
        self._reverse_order = lfEval("get(g:, 'Lf_ReverseOrder', 0)") == '1'
        self._last_reverse_order = self._reverse_order
        self._orig_pos = () # (tabpage, window, buffer)
        self._running_status = 0
        self._cursor_row = None
        self._help_length = None
        self._current_working_directory = None
        self._cur_buffer_name_ignored = False
        self._ignore_cur_buffer_name = lfEval("get(g:, 'Lf_IgnoreCurrentBufferName', 0)") == '1' \
                                            and self._category in ["File"]
        self._popup_winid = 0
        self._popup_instance = LfPopupInstance()
        self._win_pos = None
        self._highlightStl()

    def _initStlVar(self):
        if int(lfEval("!exists('g:Lf_{}_StlCategory')".format(self._category))):
            lfCmd("let g:Lf_{}_StlCategory = '-'".format(self._category))
            lfCmd("let g:Lf_{}_StlMode = '-'".format(self._category))
            lfCmd("let g:Lf_{}_StlCwd= '-'".format(self._category))
            lfCmd("let g:Lf_{}_StlRunning = ':'".format(self._category))
            lfCmd("let g:Lf_{}_StlTotal = '0'".format(self._category))
            lfCmd("let g:Lf_{}_StlLineNumber = '1'".format(self._category))
            lfCmd("let g:Lf_{}_StlResultsCount = '0'".format(self._category))

        stl = "%#Lf_hl_{0}_stlName# LeaderF "
        stl += "%#Lf_hl_{0}_stlSeparator0#%{{g:Lf_StlSeparator.left}}"
        stl += "%#Lf_hl_{0}_stlCategory# %{{g:Lf_{0}_StlCategory}} "
        stl += "%#Lf_hl_{0}_stlSeparator1#%{{g:Lf_StlSeparator.left}}"
        stl += "%#Lf_hl_{0}_stlMode# %(%{{g:Lf_{0}_StlMode}}%) "
        stl += "%#Lf_hl_{0}_stlSeparator2#%{{g:Lf_StlSeparator.left}}"
        stl += "%#Lf_hl_{0}_stlCwd# %<%{{g:Lf_{0}_StlCwd}} "
        stl += "%#Lf_hl_{0}_stlSeparator3#%{{g:Lf_StlSeparator.left}}"
        stl += "%=%#Lf_hl_{0}_stlBlank#"
        stl += "%#Lf_hl_{0}_stlSeparator4#%{{g:Lf_StlSeparator.right}}"
        if self._reverse_order:
            stl += "%#Lf_hl_{0}_stlLineInfo# %{{g:Lf_{0}_StlLineNumber}}/%{{g:Lf_{0}_StlResultsCount}} "
        else:
            stl += "%#Lf_hl_{0}_stlLineInfo# %l/%{{g:Lf_{0}_StlResultsCount}} "
        stl += "%#Lf_hl_{0}_stlSeparator5#%{{g:Lf_StlSeparator.right}}"
        stl += "%#Lf_hl_{0}_stlTotal# Total%{{g:Lf_{0}_StlRunning}} %{{g:Lf_{0}_StlTotal}} "
        self._stl = stl.format(self._category)

    def _highlightStl(self):
        lfCmd("call leaderf#colorscheme#highlight('{}')".format(self._category))

    def _setAttributes(self):
        lfCmd("setlocal nobuflisted")
        lfCmd("setlocal buftype=nofile")
        lfCmd("setlocal bufhidden=hide")
        lfCmd("setlocal undolevels=-1")
        lfCmd("setlocal noswapfile")
        lfCmd("setlocal nolist")
        lfCmd("setlocal norelativenumber")
        lfCmd("setlocal nospell")
        lfCmd("setlocal wrap")
        lfCmd("setlocal nofoldenable")
        lfCmd("setlocal foldmethod=manual")
        lfCmd("setlocal shiftwidth=4")
        lfCmd("setlocal cursorline")
        if self._reverse_order:
            lfCmd("setlocal nonumber")
            lfCmd("setlocal foldcolumn=1")
            lfCmd("setlocal winfixheight")
        else:
            lfCmd("setlocal number")
            lfCmd("setlocal foldcolumn=0")
            lfCmd("setlocal nowinfixheight")
        lfCmd("setlocal filetype=leaderf")

    def _setStatusline(self):
        if self._win_pos == 'popup':
            self._initStlVar()
            return

        self._initStlVar()
        self.window.options["statusline"] = self._stl
        lfCmd("redrawstatus")
        if not self._is_autocmd_set:
            self._is_autocmd_set = True
            lfCmd("augroup Lf_{}_Colorscheme".format(self._category))
            lfCmd("autocmd ColorScheme * call leaderf#colorscheme#setStatusline({}, '{}')"
                  .format(self.buffer.number, self._stl))
            lfCmd("autocmd WinEnter,FileType * call leaderf#colorscheme#setStatusline({}, '{}')"
                  .format(self.buffer.number, self._stl))
            lfCmd("augroup END")

    def _createPopupWindow(self):
        if self._window_object is not None and type(self._window_object) != type(vim.current.window): # type is PopupWindow
            if self._window_object.tabpage == vim.current.tabpage:
                if self._popup_winid > 0 and self._window_object.valid: # invalid if cleared by popup_clear()
                    self._popup_instance.show()
                    return
            else:
                self._popup_instance.close()

        buf_number = int(lfEval("bufnr('{}', 1)".format(self._buffer_name)))

        if lfEval("has('nvim')") == '1':
            self._win_pos = "floatwin"

            width = int(lfEval("get(g:, 'Lf_PreviewPopupWidth', 0)"))
            if width == 0:
                width = int(lfEval("&columns"))//2
            else:
                width = min(width, int(lfEval("&columns")))
            maxheight = int(lfEval("&lines - (line('w$') - line('.')) - 3"))
            maxheight -= int(self._getInstance().window.height) - int(lfEval("(line('w$') - line('w0') + 1)"))
            relative = 'editor'
            anchor = "SW"
            row = maxheight
            lfCmd("call bufload(%d)" % buf_number)
            buffer_len = len(vim.buffers[buf_number])
            height = min(maxheight, buffer_len)
            pos = lfEval("get(g:, 'Lf_PreviewHorizontalPosition', 'cursor')")
            if pos.lower() == 'center':
                col = (int(lfEval("&columns")) - width) // 2
            elif pos.lower() == 'left':
                col = 0
            elif pos.lower() == 'right':
                col = int(lfEval("&columns")) - width
            else:
                relative = 'cursor'
                row = 0
                col = 0

            if maxheight < int(lfEval("&lines"))//2 - 2:
                anchor = "NW"
                if relative == 'cursor':
                    row = 1
                else:
                    row = maxheight + 1
                height = min(int(lfEval("&lines")) - maxheight - 3, buffer_len)

            config = {
                    "relative": relative,
                    "anchor"  : anchor,
                    "height"  : height,
                    "width"   : width,
                    "row"     : row,
                    "col"     : col
                    }
            self._preview_winid = int(lfEval("nvim_open_win(%d, 0, %s)" % (buf_number, str(config))))
            lfCmd("call nvim_win_set_option(%d, 'number', v:true)" % self._preview_winid)
            lfCmd("call nvim_win_set_option(%d, 'cursorline', v:true)" % self._preview_winid)
            if buffer_len >= line_nr > 0:
                lfCmd("""call nvim_win_set_cursor(%d, [%d, 1])""" % (self._preview_winid, line_nr))
        else:
            self._win_pos = "popup"

            width = int(lfEval("get(g:, 'Lf_PopupWidth', 0)"))
            if width == 0:
                maxwidth = int(int(lfEval("&columns")) * 2 // 3)
            else:
                maxwidth = min(width, int(lfEval("&columns")))

            height = int(lfEval("get(g:, 'Lf_PopupHeight', 0)"))
            if height == 0:
                maxheight = int(int(lfEval("&lines")) * 0.4)
            else:
                maxheight = min(height, int(lfEval("&lines")))

            position = [int(i) for i in lfEval("get(g:, 'Lf_PopupPosition', [0, 0])")]
            if position == [0, 0]:
                line = (int(lfEval("&lines")) - maxheight) // 2
                col = (int(lfEval("&columns")) - maxwidth) // 2
            else:
                line, col = position
                line = min(line, int(lfEval("&lines")) - maxheight)
                col = min(col, int(lfEval("&columns")) - maxwidth)

            if line <= 0:
                line = 1

            if col <= 0:
                col = 1

            options = {
                    "maxwidth":        maxwidth,
                    "minwidth":        maxwidth,
                    "maxheight":       max(maxheight - 1, 1), # there is an input window above
                    "zindex":          20480,
                    "pos":             "topleft",
                    "line":            line + 1,      # there is an input window above
                    "col":             col,
                    "padding":         [0, 0, 0, 1],
                    "scrollbar":       0,
                    "mapping":         0,
                    # "border":          [0, 1, 0, 0],
                    # "borderchars":     [' '],
                    # "borderhighlight": ["Lf_hl_previewTitle"],
                    "filter":          "leaderf#PopupFilter",
                    }

            lfCmd("silent let winid = popup_create(%d, %s)" % (buf_number, str(options)))
            self._popup_winid = int(lfEval("winid"))
            lfCmd("call win_execute(%d, 'setlocal nobuflisted')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal buftype=nofile')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal bufhidden=hide')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal undolevels=-1')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal noswapfile')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal nolist')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal number norelativenumber')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal nospell')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal nofoldenable')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal foldmethod=manual')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal shiftwidth=4')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal cursorline')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal foldcolumn=0')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal filetype=leaderf')" % self._popup_winid)
            lfCmd("call win_execute(%d, 'setlocal wincolor=Lf_hl_popup_window')" % self._popup_winid)

            self._tabpage_object = vim.current.tabpage
            self._buffer_object = vim.buffers[buf_number]
            self._window_object = PopupWindow(self._popup_winid, self._buffer_object, self._tabpage_object)
            self._popup_instance.content_win = self._window_object

            input_win_options = {
                    "maxwidth":        maxwidth,
                    "minwidth":        maxwidth,
                    "maxheight":       1,
                    "zindex":          20480,
                    "pos":             "topleft",
                    "line":            line,
                    "col":             col,
                    "padding":         [0, 0, 0, 1],
                    "scrollbar":       0,
                    "mapping":         0,
                    # "border":          [0, 1, 0, 0],
                    # "borderchars":     [' '],
                    # "borderhighlight": ["Lf_hl_previewTitle"],
                    # "filter":          "leaderf#PopupFilter",
                    }

            buf_number = int(lfEval("bufadd('')"))
            lfCmd("silent let winid = popup_create(%d, %s)" % (buf_number, str(input_win_options)))
            winid = int(lfEval("winid"))
            lfCmd("call win_execute(%d, 'setlocal nobuflisted')" % winid)
            lfCmd("call win_execute(%d, 'setlocal buftype=nofile')" % winid)
            lfCmd("call win_execute(%d, 'setlocal bufhidden=hide')" % winid)
            lfCmd("call win_execute(%d, 'setlocal undolevels=-1')" % winid)
            lfCmd("call win_execute(%d, 'setlocal noswapfile')" % winid)
            lfCmd("call win_execute(%d, 'setlocal nolist')" % winid)
            lfCmd("call win_execute(%d, 'setlocal nonumber norelativenumber')" % winid)
            lfCmd("call win_execute(%d, 'setlocal nospell')" % winid)
            lfCmd("call win_execute(%d, 'setlocal nofoldenable')" % winid)
            lfCmd("call win_execute(%d, 'setlocal foldmethod=manual')" % winid)
            lfCmd("call win_execute(%d, 'setlocal shiftwidth=4')" % winid)
            lfCmd("call win_execute(%d, 'setlocal nocursorline')" % winid)
            lfCmd("call win_execute(%d, 'setlocal foldcolumn=0')" % winid)
            lfCmd("call win_execute(%d, 'setlocal wincolor=Statusline')" % winid)
            lfCmd("call win_execute(%d, 'setlocal filetype=leaderf')" % winid)

            self._popup_instance.input_win = PopupWindow(winid, vim.buffers[buf_number], vim.current.tabpage)

            if lfEval("get(g:, 'Lf_ShowPopupStatusline', 0)") == '1':
                input_win_options = {
                        "maxwidth":        maxwidth,
                        "minwidth":        maxwidth,
                        "maxheight":       1,
                        "zindex":          20480,
                        "pos":             "topleft",
                        "line":            line,
                        "col":             col,
                        "padding":         [0, 0, 0, 1],
                        "scrollbar":       0,
                        "mapping":         0,
                        # "border":          [0, 1, 0, 0],
                        # "borderchars":     [' '],
                        # "borderhighlight": ["Lf_hl_previewTitle"],
                        # "filter":          "leaderf#PopupFilter",
                        }

                buf_number = int(lfEval("bufadd('')"))
                lfCmd("silent let winid = popup_create(%d, %s)" % (buf_number, str(input_win_options)))
                winid = int(lfEval("winid"))
                lfCmd("call win_execute(%d, 'setlocal nobuflisted')" % winid)
                lfCmd("call win_execute(%d, 'setlocal buftype=nofile')" % winid)
                lfCmd("call win_execute(%d, 'setlocal bufhidden=hide')" % winid)
                lfCmd("call win_execute(%d, 'setlocal undolevels=-1')" % winid)
                lfCmd("call win_execute(%d, 'setlocal noswapfile')" % winid)
                lfCmd("call win_execute(%d, 'setlocal nolist')" % winid)
                lfCmd("call win_execute(%d, 'setlocal nonumber norelativenumber')" % winid)
                lfCmd("call win_execute(%d, 'setlocal nospell')" % winid)
                lfCmd("call win_execute(%d, 'setlocal nofoldenable')" % winid)
                lfCmd("call win_execute(%d, 'setlocal foldmethod=manual')" % winid)
                lfCmd("call win_execute(%d, 'setlocal shiftwidth=4')" % winid)
                lfCmd("call win_execute(%d, 'setlocal nocursorline')" % winid)
                lfCmd("call win_execute(%d, 'setlocal foldcolumn=0')" % winid)
                lfCmd("call win_execute(%d, 'setlocal wincolor=Statusline')" % winid)
                lfCmd("call win_execute(%d, 'setlocal filetype=leaderf')" % winid)

                self._popup_instance.input_win = PopupWindow(winid, vim.buffers[buf_number], vim.current.tabpage)

            lfCmd("""call leaderf#ResetCallback(%d, function('leaderf#PopupClosed', [%s]))"""
                    % (self._popup_winid, str(self._popup_instance.getWinIdList())))

    def _createBufWindow(self, win_pos):
        self._win_pos = win_pos

        saved_eventignore = vim.options['eventignore']
        vim.options['eventignore'] = 'all'
        try:
            orig_win = vim.current.window
            for w in vim.windows:
                vim.current.window = w
                if lfEval("exists('w:lf_win_view')") == '0':
                    lfCmd("let w:lf_win_view = {}")
                lfCmd("let w:lf_win_view['%s'] = winsaveview()" % self._category)
        finally:
            vim.current.window = orig_win
            vim.options['eventignore'] = saved_eventignore

        if win_pos != 'fullScreen':
            self._restore_sizes = lfEval("winrestcmd()")
            self._orig_win_count = len(vim.windows)

        """
        https://github.com/vim/vim/issues/1737
        https://github.com/vim/vim/issues/1738
        """
        # clear the buffer first to avoid a flash
        if self._buffer_object is not None and self._buffer_object.valid \
                and lfEval("g:Lf_RememberLastSearch") == '0' \
                and "--append" not in self._arguments \
                and "--recall" not in self._arguments:
            self.buffer.options['modifiable'] = True
            del self._buffer_object[:]

        if win_pos == 'bottom':
            lfCmd("silent! noa keepa keepj bo sp %s" % self._buffer_name)
            if self._win_height >= 1:
                lfCmd("resize %d" % self._win_height)
            elif self._win_height > 0:
                lfCmd("resize %d" % (int(lfEval("&lines")) * self._win_height))
        elif win_pos == 'belowright':
            lfCmd("silent! noa keepa keepj bel sp %s" % self._buffer_name)
            if self._win_height >= 1:
                lfCmd("resize %d" % self._win_height)
            elif self._win_height > 0:
                lfCmd("resize %d" % (int(lfEval("&lines")) * self._win_height))
        elif win_pos == 'aboveleft':
            lfCmd("silent! noa keepa keepj abo sp %s" % self._buffer_name)
            if self._win_height >= 1:
                lfCmd("resize %d" % self._win_height)
            elif self._win_height > 0:
                lfCmd("resize %d" % (int(lfEval("&lines")) * self._win_height))
        elif win_pos == 'top':
            lfCmd("silent! noa keepa keepj to sp %s" % self._buffer_name)
            if self._win_height >= 1:
                lfCmd("resize %d" % self._win_height)
            elif self._win_height > 0:
                lfCmd("resize %d" % (int(lfEval("&lines")) * self._win_height))
        elif win_pos == 'fullScreen':
            lfCmd("silent! noa keepa keepj $tabedit %s" % self._buffer_name)
        elif win_pos == 'left':
            lfCmd("silent! noa keepa keepj to vsp %s" % self._buffer_name)
        elif win_pos == 'right':
            lfCmd("silent! noa keepa keepj bo vsp %s" % self._buffer_name)
        else:
            lfCmd("echoe 'Wrong value of g:Lf_WindowPosition'")

        self._tabpage_object = vim.current.tabpage
        self._window_object = vim.current.window
        self._initial_win_height = self._window_object.height
        if self._reverse_order and "--recall" not in self._arguments:
            self._window_object.height = 1

        if self._buffer_object is None or not self._buffer_object.valid:
            self._buffer_object = vim.current.buffer
            lfCmd("augroup Lf_{}_Colorscheme".format(self._category))
            lfCmd("autocmd!")
            lfCmd("autocmd ColorScheme * call leaderf#colorscheme#highlight('{}')"
                  .format(self._category))
            lfCmd("autocmd ColorScheme * call leaderf#colorscheme#highlightMode('{0}', g:Lf_{0}_StlMode)"
                  .format(self._category))
            lfCmd("autocmd ColorScheme <buffer> doautocmd syntax")
            lfCmd("autocmd CursorMoved <buffer> let g:Lf_{}_StlLineNumber = 1 + line('$') - line('.')"
                  .format(self._category))
            lfCmd("autocmd VimResized * let g:Lf_VimResized = 1")
            lfCmd("augroup END")

        saved_eventignore = vim.options['eventignore']
        vim.options['eventignore'] = 'all'
        try:
            orig_win = vim.current.window
            for w in vim.windows:
                vim.current.window = w
                if lfEval("exists('w:lf_win_view')") != '0' and lfEval("has_key(w:lf_win_view, '%s')" % self._category) != '0':
                    lfCmd("call winrestview(w:lf_win_view['%s'])" % self._category)
        finally:
            vim.current.window = orig_win
            vim.options['eventignore'] = saved_eventignore

    def _enterOpeningBuffer(self):
        if (self._tabpage_object and self._tabpage_object.valid
            and self._window_object and self._window_object.valid and self._window_object.number != 0 # the number may be 0 although PopupWindow is valid because of popup_hide()
            and self._window_object.buffer == self._buffer_object):
            vim.current.tabpage = self._tabpage_object
            vim.current.window = self._window_object
            self._after_enter()
            return True
        return False

    def setArguments(self, arguments):
        self._last_reverse_order = self._reverse_order
        self._arguments = arguments
        if "--reverse" in self._arguments or lfEval("get(g:, 'Lf_ReverseOrder', 0)") == '1':
            self._reverse_order = True
        else:
            self._reverse_order = False

    def ignoreReverse(self):
        self._reverse_order = False

    def useLastReverseOrder(self):
        self._reverse_order = self._last_reverse_order

    def setStlCategory(self, category):
        lfCmd("let g:Lf_{}_StlCategory = '{}'".format(self._category, category) )

    def setStlMode(self, mode):
        lfCmd("let g:Lf_{}_StlMode = '{}'".format(self._category, mode))
        lfCmd("call leaderf#colorscheme#highlightMode('{0}', g:Lf_{0}_StlMode)"
              .format(self._category))

    def setStlCwd(self, cwd):
        lfCmd("let g:Lf_{}_StlCwd = '{}'".format(self._category, cwd))

    def setStlTotal(self, total):
        lfCmd("let g:Lf_{}_StlTotal = '{}'".format(self._category, total))

    def setStlResultsCount(self, count, check_ignored=False):
        if check_ignored and self._cur_buffer_name_ignored:
            count -= 1
        lfCmd("let g:Lf_{}_StlResultsCount = '{}'".format(self._category, count))
        if lfEval("has('nvim')") == '1':
            lfCmd("redrawstatus")

        if self._win_pos == 'popup':
            self._cli._buildPopupPrompt()

    def setStlRunning(self, running):
        if self._win_pos == 'popup':
            if running:
                lfCmd("let g:Lf_{}_StlRunning = 1".format(self._category))
            else:
                lfCmd("let g:Lf_{}_StlRunning = 0".format(self._category))
            return

        if running:
            status = (':', ' ')
            lfCmd("let g:Lf_{}_StlRunning = '{}'".format(self._category, status[self._running_status]))
            self._running_status = (self._running_status + 1) & 1
        else:
            self._running_status = 0
            lfCmd("let g:Lf_{}_StlRunning = ':'".format(self._category))

    def enterBuffer(self, win_pos):
        if self._enterOpeningBuffer():
            return

        lfCmd("let g:Lf_{}_StlLineNumber = '1'".format(self._category))
        self._orig_pos = (vim.current.tabpage, vim.current.window, vim.current.buffer)
        self._orig_cursor = vim.current.window.cursor
        self._orig_buffer_name = os.path.normpath(lfDecode(vim.current.buffer.name))
        if lfEval("g:Lf_ShowRelativePath") == '1':
            try:
                self._orig_buffer_name = os.path.relpath(self._orig_buffer_name)
            except ValueError:
                pass
        self._orig_buffer_name = lfEncode(self._orig_buffer_name)

        self._before_enter()

        if win_pos == 'popup':
            self._orig_win_nr = vim.current.window.number
            self._orig_win_id = lfWinId(self._orig_win_nr)
            self._createPopupWindow()
        elif win_pos == 'fullScreen':
            self._orig_tabpage = vim.current.tabpage
            if len(vim.tabpages) < 2:
                lfCmd("set showtabline=0")
            self._createBufWindow(win_pos)
            self._setAttributes()
        else:
            self._orig_win_nr = vim.current.window.number
            self._orig_win_id = lfWinId(self._orig_win_nr)
            self._createBufWindow(win_pos)
            self._setAttributes()

        self._setStatusline()
        self._after_enter()

    def exitBuffer(self):
        self._before_exit()

        if self._win_pos == 'popup':
            self._popup_instance.hide()
            self._after_exit()
            return
        elif self._win_pos == 'fullScreen':
            try:
                lfCmd("tabclose!")
                vim.current.tabpage = self._orig_tabpage
            except:
                lfCmd("new | only")

            lfCmd("set showtabline=%d" % self._show_tabline)
        else:
            saved_eventignore = vim.options['eventignore']
            vim.options['eventignore'] = 'all'
            try:
                orig_win = vim.current.window
                for w in vim.windows:
                    vim.current.window = w
                    if lfEval("exists('w:lf_win_view')") == '0':
                        lfCmd("let w:lf_win_view = {}")
                    lfCmd("let w:lf_win_view['%s'] = winsaveview()" % self._category)
            finally:
                vim.current.window = orig_win
                vim.options['eventignore'] = saved_eventignore

            if len(vim.windows) > 1:
                lfCmd("silent! hide")
                if self._orig_win_id is not None:
                    lfCmd("call win_gotoid(%d)" % self._orig_win_id)
                else:
                    # 'silent!' is used to skip error E16.
                    lfCmd("silent! exec '%d wincmd w'" % self._orig_win_nr)
                if lfEval("get(g:, 'Lf_VimResized', 0)") == '0' \
                        and self._orig_win_count == len(vim.windows):
                    lfCmd(self._restore_sizes) # why this line does not take effect?
                                               # it's weird. repeat 4 times
                    lfCmd(self._restore_sizes) # fix issue #102
                    lfCmd(self._restore_sizes) # fix issue #102
                    lfCmd(self._restore_sizes) # fix issue #102
                    lfCmd(self._restore_sizes) # fix issue #102
            else:
                lfCmd("bd")

            saved_eventignore = vim.options['eventignore']
            vim.options['eventignore'] = 'all'
            try:
                orig_win = vim.current.window
                for w in vim.windows:
                    vim.current.window = w
                    if lfEval("exists('w:lf_win_view')") != '0' and lfEval("has_key(w:lf_win_view, '%s')" % self._category) != '0':
                        lfCmd("call winrestview(w:lf_win_view['%s'])" % self._category)
            finally:
                vim.current.window = orig_win
                vim.options['eventignore'] = saved_eventignore

        lfCmd("echo")

        self._after_exit()

    def _actualLength(self, buffer):
        num = 0
        columns = int(lfEval("&columns"))
        for i in buffer:
            num += (int(lfEval("strdisplaywidth('%s')" % escQuote(i))) + columns - 1)// columns
        return num

    def setBuffer(self, content, need_copy=False):
        self._cur_buffer_name_ignored = False
        if self._ignore_cur_buffer_name:
            if self._orig_buffer_name in content[:self._window_object.height]:
                self._cur_buffer_name_ignored = True
                if need_copy:
                    content = content[:]
                content.remove(self._orig_buffer_name)
            elif os.name == 'nt':
                buffer_name = self._orig_buffer_name.replace('\\', '/')
                if buffer_name in content[:self._window_object.height]:
                    self._cur_buffer_name_ignored = True
                    if need_copy:
                        content = content[:]
                    content.remove(buffer_name)

        self.buffer.options['modifiable'] = True
        if lfEval("has('nvim')") == '1':
            if len(content) > 0 and len(content[0]) != len(content[0].rstrip("\r\n")):
                # NvimError: string cannot contain newlines
                content = [ line.rstrip("\r\n") for line in content ]
        try:
            if self._reverse_order:
                orig_row = self._window_object.cursor[0]
                orig_buf_len = len(self._buffer_object)

                self._buffer_object[:] = content[::-1]
                buffer_len = len(self._buffer_object)
                if buffer_len < self._initial_win_height:
                    if "--nowrap" not in self._arguments:
                        self._window_object.height = min(self._initial_win_height, self._actualLength(self._buffer_object))
                    else:
                        self._window_object.height = buffer_len
                elif self._window_object.height < self._initial_win_height:
                    self._window_object.height = self._initial_win_height

                try:
                    self._window_object.cursor = (orig_row + buffer_len - orig_buf_len, 0)
                    # if self._window_object.cursor == (buffer_len, 0):
                    #     lfCmd("normal! zb")
                except vim.error:
                    self._window_object.cursor = (buffer_len, 0)
                    # lfCmd("normal! zb")

                self.setLineNumber()
            else:
                self._buffer_object[:] = content
        finally:
            self.buffer.options['modifiable'] = False

    def appendBuffer(self, content):
        self.buffer.options['modifiable'] = True
        if lfEval("has('nvim')") == '1':
            if len(content) > 0 and len(content[0]) != len(content[0].rstrip("\r\n")):
                # NvimError: string cannot contain newlines
                content = [ line.rstrip("\r\n") for line in content ]

        try:
            if self._reverse_order:
                orig_row = self._window_object.cursor[0]
                orig_buf_len = len(self._buffer_object)

                if self.empty():
                    self._buffer_object[:] = content[::-1]
                else:
                    self._buffer_object.append(content[::-1], 0)
                buffer_len = len(self._buffer_object)
                if buffer_len < self._initial_win_height:
                    if "--nowrap" not in self._arguments:
                        self._window_object.height = min(self._initial_win_height, self._actualLength(self._buffer_object))
                    else:
                        self._window_object.height = buffer_len
                elif self._window_object.height < self._initial_win_height:
                    self._window_object.height = self._initial_win_height

                try:
                    self._window_object.cursor = (orig_row + buffer_len - orig_buf_len, 0)
                    # if self._window_object.cursor == (buffer_len, 0):
                    #     lfCmd("normal! zb")
                except vim.error:
                    self._window_object.cursor = (buffer_len, 0)
                    # lfCmd("normal! zb")

                self.setLineNumber()
            else:
                if self.empty():
                    self._buffer_object[:] = content
                else:
                    self._buffer_object.append(content)
        finally:
            self.buffer.options['modifiable'] = False

    def clearBuffer(self):
        self.buffer.options['modifiable'] = True
        if self._buffer_object and self._buffer_object.valid:
            del self._buffer_object[:]
        self.buffer.options['modifiable'] = False

    def appendLine(self, line):
        self._buffer_object.append(line)

    def initBuffer(self, content, unit, set_content):
        if isinstance(content, list):
            self.setBuffer(content, need_copy=True)
            self.setStlTotal(len(content)//unit)
            self.setStlResultsCount(len(content)//unit, True)
            return content

        self.buffer.options['modifiable'] = True
        self._buffer_object[:] = []

        try:
            start = time.time()
            status_start = start
            cur_content = []
            for line in content:
                cur_content.append(line)
                if time.time() - start > 0.1:
                    start = time.time()
                    if len(self._buffer_object) <= self._window_object.height:
                        self.setBuffer(cur_content, need_copy=True)
                        if self._reverse_order:
                            lfCmd("normal! G")

                    if time.time() - status_start > 0.45:
                        status_start = time.time()
                        self.setStlRunning(True)
                    self.setStlTotal(len(cur_content)//unit)
                    self.setStlResultsCount(len(cur_content)//unit)
                    if self._win_pos != 'popup':
                        lfCmd("redrawstatus")
            self.setBuffer(cur_content, need_copy=True)
            self.setStlTotal(len(self._buffer_object)//unit)
            self.setStlRunning(False)
            self.setStlResultsCount(len(self._buffer_object)//unit, True)
            if self._win_pos != 'popup':
                lfCmd("redrawstatus")
            set_content(cur_content)
        except vim.error: # neovim <C-C>
            pass
        except KeyboardInterrupt: # <C-C>
            pass

        return cur_content

    @property
    def tabpage(self):
        return self._tabpage_object

    @property
    def window(self):
        return self._window_object

    @property
    def buffer(self):
        return self._buffer_object

    @property
    def currentLine(self):
        if self._win_pos == 'popup':
            return self._buffer_object[self._window_object.cursor[0] - 1]
        else:
            return vim.current.line if self._buffer_object == vim.current.buffer else None

    def empty(self):
        return len(self._buffer_object) == 1 and self._buffer_object[0] == ''

    def getCurrentPos(self):
        return self._window_object.cursor

    def getOriginalPos(self):
        return self._orig_pos

    def getOriginalCursor(self):
        return self._orig_cursor

    def getInitialWinHeight(self):
        if self._reverse_order:
            return self._initial_win_height
        else:
            return 200

    def isReverseOrder(self):
        return self._reverse_order

    def isLastReverseOrder(self):
        return self._last_reverse_order

    def setLineNumber(self):
        if self._reverse_order:
            line_nr = 1 + len(self._buffer_object) - self._window_object.cursor[0]
            lfCmd("let g:Lf_{}_StlLineNumber = '{}'".format(self._category, line_nr))

    def setCwd(self, cwd):
        self._current_working_directory = cwd

    def getCwd(self):
        return self._current_working_directory

    @property
    def cursorRow(self):
        return self._cursor_row

    @cursorRow.setter
    def cursorRow(self, row):
        self._cursor_row = row

    @property
    def helpLength(self):
        return self._help_length

    @helpLength.setter
    def helpLength(self, length):
        self._help_length = length

    def gotoOriginalWindow(self):
        if self._orig_win_id is not None:
            lfCmd("call win_gotoid(%d)" % self._orig_win_id)
        else:
            # 'silent!' is used to skip error E16.
            lfCmd("silent! exec '%d wincmd w'" % self._orig_win_nr)

    def getWinPos(self):
        return self._win_pos

    def getPopupWinId(self):
        return self._popup_winid

    def getPopupInstance(self):
        return self._popup_instance

#  vim: set ts=4 sw=4 tw=0 et :
