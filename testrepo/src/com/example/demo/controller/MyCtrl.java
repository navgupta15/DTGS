package com.example.demo.controller;

import org.springframework.web.bind.annotation.*;

import com.example.demo.vo.MyTestVo;

@RestController
@RequestMapping("/api/pets")
public class MyCtrl {
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    public String getPet(@PathVariable String id, MyTestVo vo) {
        return vo.getName();
    }

    @RequestMapping(value = "/add", method = RequestMethod.POST)
    public int addPet(MyTestVo vo) {
        return vo.getAge();
    }

    @RequestMapping(value = "/del", method = RequestMethod.DELETE)
    public int delPet(@RequestParam("id") String id) {
        return 1;
    }

    @RequestMapping(value = "/update", method = RequestMethod.PUT)
    public int updatePet(@RequestParam("id") String id, MyTestVo vo) {
        return 1;
    }
}
